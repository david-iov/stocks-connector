"""Turn indicators into per-ticker short-term signals and a composite call."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
from .fundamentals import Fundamentals
from . import indicators as ind


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class SignalComponent:
    name: str
    score: float          # normalised contribution in [-1, 1]
    weighted: float       # score * configured weight
    reason: str


@dataclass
class TickerSignal:
    ticker: str
    price: float
    change_pct: float     # last-bar percent change
    rsi: float
    composite: float
    action: str
    components: list[SignalComponent] = field(default_factory=list)
    spark: list[float] = field(default_factory=list)  # recent closes for a sparkline
    returns: dict[str, float] = field(default_factory=dict)  # {"1d":%, "7d":%, "30d":%}
    entry: str = ""          # "good time to buy?" verdict label
    entry_note: str = ""     # one-line rationale
    entry_level: str = "neutral"  # good | wait | no | neutral (drives UI colour)
    # Fundamental / analyst layer (None when unavailable, e.g. ETFs / small caps)
    analyst_label: str | None = None    # compact "Buy +38%" style summary
    analyst_level: str = "none"         # buy | hold | sell | none (drives colour)
    upside_pct: float | None = None     # analyst mean target vs price, %
    earnings_days: int | None = None    # days to next earnings (risk flag)
    context: list[SignalComponent] = field(default_factory=list)  # notable fundamental chips
    fundamentals: dict = field(default_factory=dict)  # raw-ish fields for detail
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


_ACTION_ORDER = {
    "STRONG BUY": 4,
    "BUY": 3,
    "HOLD": 2,
    "SELL": 1,
    "STRONG SELL": 0,
}


def action_rank(action: str) -> int:
    """Sort key so the most bullish calls surface first."""
    return _ACTION_ORDER.get(action, 2)


def _label(score: float, cfg: Config) -> str:
    t = cfg.thresholds
    if score >= t.strong_buy:
        return "STRONG BUY"
    if score >= t.buy:
        return "BUY"
    if score <= t.strong_sell:
        return "STRONG SELL"
    if score <= t.sell:
        return "SELL"
    return "HOLD"


def _rsi_component(rsi_now: float, cfg: Config) -> SignalComponent:
    p = cfg.indicators
    # Below oversold is bullish (mean-reversion bounce), above overbought bearish.
    midpoint = (p.rsi_overbought + p.rsi_oversold) / 2
    half_span = (p.rsi_overbought - p.rsi_oversold) / 2
    score = _clamp((midpoint - rsi_now) / half_span)
    if rsi_now <= p.rsi_oversold:
        reason = f"RSI {rsi_now:.0f} — oversold, bounce likely"
    elif rsi_now >= p.rsi_overbought:
        reason = f"RSI {rsi_now:.0f} — overbought, pullback risk"
    elif score > 0.3:  # leaning toward oversold — matches the UI's colour band
        reason = f"RSI {rsi_now:.0f} — soft, room to rise"
    elif score < -0.3:
        reason = f"RSI {rsi_now:.0f} — elevated, stretched"
    else:
        reason = f"RSI {rsi_now:.0f} — neutral"
    return SignalComponent("rsi", score, score * cfg.weights.rsi, reason)


def _macd_component(macd_df: pd.DataFrame, cfg: Config) -> SignalComponent:
    hist = macd_df["hist"]
    hist_now = float(hist.iloc[-1])
    # Normalise the histogram by its own recent volatility so the score is scale-free.
    scale = float(hist.tail(60).abs().mean()) or 1e-9
    score = _clamp(hist_now / (2 * scale))

    crossed_up = hist_now > 0 >= float(hist.iloc[-2])
    crossed_down = hist_now < 0 <= float(hist.iloc[-2])
    if crossed_up:
        reason = "MACD just crossed up — momentum turning positive"
        score = max(score, 0.6)
    elif crossed_down:
        reason = "MACD just crossed down — momentum turning negative"
        score = min(score, -0.6)
    else:
        reason = "MACD momentum " + ("rising" if hist_now >= 0 else "falling")
    return SignalComponent("macd", score, score * cfg.weights.macd, reason)


def _ma_cross_component(
    fast_sma: pd.Series, slow_sma: pd.Series, cfg: Config
) -> SignalComponent:
    fast_now, slow_now = float(fast_sma.iloc[-1]), float(slow_sma.iloc[-1])
    gap = (fast_now - slow_now) / slow_now if slow_now else 0.0
    score = _clamp(gap / 0.03)  # ~3% separation saturates the signal

    fast_prev, slow_prev = float(fast_sma.iloc[-2]), float(slow_sma.iloc[-2])
    golden = fast_now > slow_now and fast_prev <= slow_prev
    death = fast_now < slow_now and fast_prev >= slow_prev
    f, s = cfg.indicators.sma_fast, cfg.indicators.sma_slow
    if golden:
        reason = f"golden cross — {f}d avg crossed above {s}d avg"
        score = max(score, 0.7)
    elif death:
        reason = f"death cross — {f}d avg crossed below {s}d avg"
        score = min(score, -0.7)
    else:
        trend = "above" if fast_now >= slow_now else "below"
        reason = f"{f}d avg {trend} {s}d avg — {'up' if fast_now >= slow_now else 'down'}trend"
    return SignalComponent("ma_cross", score, score * cfg.weights.ma_cross, reason)


def _trend_component(close: pd.Series, fast_sma: pd.Series, cfg: Config) -> SignalComponent:
    price = float(close.iloc[-1])
    sma_now = float(fast_sma.iloc[-1])
    gap = (price - sma_now) / sma_now if sma_now else 0.0
    score = _clamp(gap / 0.05)  # ~5% above/below the fast SMA saturates
    where = "above" if gap >= 0 else "below"
    reason = f"price {abs(gap) * 100:.1f}% {where} its {cfg.indicators.sma_fast}d avg"
    return SignalComponent("trend", score, score * cfg.weights.trend, reason)


def _volume_component(df: pd.DataFrame, cfg: Config) -> SignalComponent:
    p = cfg.indicators
    vol = df["Volume"]
    avg = float(vol.tail(p.volume_lookback + 1).iloc[:-1].mean()) or 1e-9
    ratio = float(vol.iloc[-1]) / avg
    spike = _clamp((ratio - 1.0) / max(p.volume_spike_mult - 1.0, 1e-9), 0.0, 1.0)
    daily_ret = float(df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1.0)
    direction = 1.0 if daily_ret >= 0 else -1.0
    score = direction * spike
    if spike > 0:
        reason = f"heavy volume ({ratio:.1f}x avg) on {'an up' if direction > 0 else 'a down'} day"
    else:
        reason = f"light volume ({ratio:.1f}x avg) — move unconfirmed"
    return SignalComponent("volume", score, score * cfg.weights.volume, reason)


def _returns(close: pd.Series) -> dict[str, float]:
    """Percent change over calendar windows, using the close on-or-before each date."""
    out: dict[str, float] = {}
    last = float(close.iloc[-1])
    last_date = close.index[-1]
    for label, days in (("1d", 1), ("7d", 7), ("30d", 30)):
        target = last_date - pd.Timedelta(days=days)
        prior = close.loc[:target]
        if prior.empty:
            continue
        out[label] = (last / float(prior.iloc[-1]) - 1.0) * 100
    return out


_RATING_SHORT = {
    "strong_buy": "Strong Buy", "buy": "Buy", "outperform": "Buy",
    "hold": "Hold", "neutral": "Hold",
    "underperform": "Sell", "sell": "Sell", "strong_sell": "Sell",
}


def _analyst_summary(f: Fundamentals | None) -> tuple[str | None, str, float | None]:
    """Compact analyst read: (label, level, upside_pct). level in buy|hold|sell|none."""
    if not f or not f.ok or f.target_mean is None or f.upside_pct is None:
        return (None, "none", None)
    up = f.upside_pct
    short = _RATING_SHORT.get(f.rating or "", "")
    if f.rating in ("strong_buy", "buy", "outperform"):
        level = "buy"
    elif f.rating in ("sell", "strong_sell", "underperform"):
        level = "sell"
    elif f.rating in ("hold", "neutral"):
        level = "hold"
    else:  # thin/no consensus — fall back to the target's implied direction
        level = "buy" if up >= 5 else ("sell" if up <= -5 else "hold")
    label = f"{short} {up:+.0f}%".strip() if short else f"{up:+.0f}%"
    return (label, level, up)


def _context_chips(f: Fundamentals | None) -> list[SignalComponent]:
    """Notable fundamental context as colour-scored chips (kept short to avoid clutter)."""
    if not f or not f.ok:
        return []
    cands: list[tuple[float, SignalComponent]] = []  # (priority, chip)

    if f.earnings_days is not None and 0 <= f.earnings_days <= 12:
        prio = 100 if f.earnings_days <= 5 else 2
        word = "today" if f.earnings_days == 0 else f"in {f.earnings_days}d"
        cands.append((prio, SignalComponent("earnings", 0.0, 0.0, f"earnings {word}")))

    if f.peg is not None and 0 < f.peg < 1:
        cands.append((5, SignalComponent("peg", 0.4, 0.0, f"PEG {f.peg:.2f} (cheap growth)")))
    elif f.peg is not None and f.peg > 3.5:
        cands.append((3, SignalComponent("peg", -0.3, 0.0, f"PEG {f.peg:.1f} (pricey)")))

    # Cap at 300% — larger figures are usually tiny-base artifacts, not signal.
    if f.revenue_growth is not None and 0.30 <= f.revenue_growth <= 3.0:
        cands.append((4, SignalComponent("growth", 0.4, 0.0, f"rev +{f.revenue_growth * 100:.0f}%")))

    if f.short_pct_float is not None and f.short_pct_float >= 0.15:
        cands.append((3, SignalComponent("short", 0.0, 0.0, f"{f.short_pct_float * 100:.0f}% short float")))

    if f.pct_from_high is not None and f.pct_from_high >= -2:
        cands.append((1, SignalComponent("range", 0.0, 0.0, "at 52w high")))
    elif f.pct_of_52w_range is not None and f.pct_of_52w_range <= 12:
        cands.append((1, SignalComponent("range", 0.0, 0.0, "near 52w low")))

    cands.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in cands[:3]]


def _entry_advice(
    rsi_now: float, composite: float, uptrend: bool, ret_1d: float,
    cfg: Config, f: Fundamentals | None, upside_pct: float | None,
) -> tuple[str, str, str]:
    """Answer 'is it a good time to buy?' by blending technical timing with the
    analyst view and an earnings-risk override.

    Returns (label, note, level) where level in {good, wait, no, neutral}.
    Priority: don't-buy-into-earnings > downtrend > overbought > over-target >
    technical entry.
    """
    p = cfg.indicators
    pulling_back = ret_1d < 0 or rsi_now <= 50
    ed = f.earnings_days if f else None

    # 1) Binary event risk: earnings within a week is a coin-flip, not an entry.
    if ed is not None and 0 <= ed <= 5:
        when = "today" if ed == 0 else f"in {ed}d"
        return (f"Wait — earnings {when}", "binary event ahead; let it clear first", "wait")

    # 2) Downtrend — direction is wrong regardless of valuation.
    if composite <= cfg.thresholds.sell:
        return ("No — downtrend", "trend is down; wait for a base to form", "no")

    # 3) Overbought — wait for a pullback.
    if rsi_now >= p.rsi_overbought:
        return ("Wait — overbought", "stretched; better entry on a pullback", "wait")

    # 4) Trading well above the analyst mean target — limited room even if up.
    if upside_pct is not None and upside_pct <= -12:
        return ("Caution — above targets",
                f"~{abs(upside_pct):.0f}% over analyst mean target", "wait")

    # 5) Technical entry, enriched with an analyst tailwind when present.
    tail = ""
    if upside_pct is not None and upside_pct >= 10:
        tail = f"; analysts see +{upside_pct:.0f}%"
    if uptrend and pulling_back:
        return ("Yes — dip buy", "pulling back within an uptrend" + tail, "good")
    if uptrend:
        return ("Buyable", "healthy uptrend, not overextended" + tail, "good")
    if composite >= cfg.thresholds.buy:
        return ("Buyable", "momentum turning up" + tail, "good")
    return ("Neutral", "no clear edge — wait for confirmation", "neutral")


def evaluate(
    ticker: str, df: pd.DataFrame, cfg: Config,
    fundamentals: Fundamentals | None = None,
) -> TickerSignal:
    """Compute indicators + composite call, blended with analyst/earnings data.

    `fundamentals` is optional: when None (e.g. in offline tests) the result is a
    pure-technical read. The engine supplies it in normal runs.
    """
    p = cfg.indicators
    close = df["Close"]

    rsi_series = ind.rsi(close, p.rsi_period)
    macd_df = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    fast_sma = ind.sma(close, p.sma_fast)
    slow_sma = ind.sma(close, p.sma_slow)

    rsi_now = float(rsi_series.iloc[-1])
    if np.isnan(rsi_now):
        return TickerSignal(
            ticker=ticker, price=float(close.iloc[-1]), change_pct=0.0,
            rsi=float("nan"), composite=0.0, action="HOLD",
            error="not enough history for indicators",
        )

    components = [
        _rsi_component(rsi_now, cfg),
        _macd_component(macd_df, cfg),
        _ma_cross_component(fast_sma, slow_sma, cfg),
        _trend_component(close, fast_sma, cfg),
        _volume_component(df, cfg),
    ]
    composite = sum(c.weighted for c in components)
    change_pct = float(close.iloc[-1] / close.iloc[-2] - 1.0) * 100
    spark = [round(float(x), 4) for x in close.tail(30)]
    returns = _returns(close)

    analyst_label, analyst_level, upside_pct = _analyst_summary(fundamentals)
    context = _context_chips(fundamentals)

    uptrend = float(fast_sma.iloc[-1]) > float(slow_sma.iloc[-1])
    entry, entry_note, entry_level = _entry_advice(
        rsi_now, composite, uptrend, returns.get("1d", change_pct),
        cfg, fundamentals, upside_pct,
    )

    from dataclasses import asdict as _asdict
    fund_dict = _asdict(fundamentals) if fundamentals and fundamentals.ok else {}

    return TickerSignal(
        ticker=ticker,
        price=float(close.iloc[-1]),
        change_pct=change_pct,
        rsi=rsi_now,
        composite=composite,
        action=_label(composite, cfg),
        components=components,
        spark=spark,
        returns=returns,
        entry=entry,
        entry_note=entry_note,
        entry_level=entry_level,
        analyst_label=analyst_label,
        analyst_level=analyst_level,
        upside_pct=round(upside_pct, 1) if upside_pct is not None else None,
        earnings_days=fundamentals.earnings_days if fundamentals else None,
        context=context,
        fundamentals=fund_dict,
    )
