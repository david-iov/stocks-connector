"""Turn indicators into per-ticker short-term signals and a composite call."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
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


def _entry_advice(
    rsi_now: float, composite: float, uptrend: bool, ret_1d: float, cfg: Config
) -> tuple[str, str, str]:
    """Answer 'is it a good time to buy?' from short-term entry timing.

    Distinct from the overall call: this is about *when* to step in, favouring
    pullbacks within uptrends and flagging extended/overbought names.
    Returns (label, note, level) where level in {good, wait, no, neutral}.
    """
    p = cfg.indicators
    pulling_back = ret_1d < 0 or rsi_now <= 50

    if composite <= cfg.thresholds.sell:
        return ("No — downtrend", "trend is down; wait for a base to form", "no")
    if rsi_now >= p.rsi_overbought:
        return ("Wait — overbought", "stretched; better entry on a pullback", "wait")
    if uptrend and pulling_back:
        return ("Yes — dip buy", "pulling back within an uptrend", "good")
    if uptrend:
        return ("Buyable", "healthy uptrend, not overextended", "good")
    if composite >= cfg.thresholds.buy:
        return ("Buyable", "momentum turning up", "good")
    return ("Neutral", "no clear edge — wait for confirmation", "neutral")


def evaluate(ticker: str, df: pd.DataFrame, cfg: Config) -> TickerSignal:
    """Compute all indicators and the composite call for one ticker's history."""
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

    uptrend = float(fast_sma.iloc[-1]) > float(slow_sma.iloc[-1])
    entry, entry_note, entry_level = _entry_advice(
        rsi_now, composite, uptrend, returns.get("1d", change_pct), cfg
    )

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
    )
