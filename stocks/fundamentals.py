"""Fundamental / analyst / earnings data via yfinance `.info`.

One request per ticker. Everything is best-effort: missing or sparse fields
(common on small caps and ETFs) come back as None and the caller degrades to a
technicals-only view. Nothing here raises on missing data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import yfinance as yf


@dataclass
class Fundamentals:
    quote_type: str | None = None          # EQUITY | ETF | ...
    # Analyst view
    rating: str | None = None              # strong_buy | buy | hold | ... | none
    num_analysts: int | None = None
    target_mean: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    upside_pct: float | None = None        # target_mean vs our price, %
    # Earnings
    earnings_days: int | None = None       # calendar days until next earnings
    earnings_date: str | None = None       # ISO date
    # 52-week range
    week52_high: float | None = None
    week52_low: float | None = None
    pct_of_52w_range: float | None = None  # 0 at low, 100 at high
    pct_from_high: float | None = None     # negative = below the high
    # Valuation / risk
    forward_pe: float | None = None
    peg: float | None = None
    revenue_growth: float | None = None    # fraction, e.g. 1.06 = +106%
    beta: float | None = None
    # Short interest
    short_pct_float: float | None = None   # fraction, e.g. 0.32 = 32%

    ok: bool = False                       # True if we got a usable info blob


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def fetch_fundamentals(ticker: str, price: float | None = None) -> Fundamentals:
    """Pull `.info` for one ticker and distil the fields we care about.

    `price` (our latest close) is used to compute upside vs the analyst target
    and the 52-week range position, so it stays consistent with the rest of the
    report. Never raises — returns an empty Fundamentals on any failure.
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception:  # noqa: BLE001 - network/parse issues are non-fatal
        return Fundamentals()

    if not info:
        return Fundamentals()

    f = Fundamentals(ok=True)
    f.quote_type = info.get("quoteType")

    px = price if price is not None else _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))

    # --- analyst view ---
    rating = info.get("recommendationKey")
    f.rating = rating if rating and rating != "none" else None
    f.num_analysts = int(info["numberOfAnalystOpinions"]) if _num(info.get("numberOfAnalystOpinions")) else None
    f.target_mean = _num(info.get("targetMeanPrice"))
    f.target_high = _num(info.get("targetHighPrice"))
    f.target_low = _num(info.get("targetLowPrice"))
    if f.target_mean and px:
        f.upside_pct = (f.target_mean / px - 1.0) * 100

    # --- earnings proximity (from the unix timestamp in .info) ---
    today = datetime.now(timezone.utc).date()
    ets = _num(info.get("earningsTimestamp"))
    if ets:
        try:
            ed = datetime.fromtimestamp(ets, tz=timezone.utc).date()
            f.earnings_date = ed.isoformat()
            f.earnings_days = (ed - today).days
        except (OverflowError, OSError, ValueError):
            pass
    # .info's timestamp is sometimes the *last* report; if it's missing or in the
    # past, fall back to the calendar for the next (future) earnings date.
    if f.earnings_days is None or f.earnings_days < 0:
        try:
            cal = tk.calendar or {}
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            future = sorted(d for d in (dates or []) if d >= today)
            if future:
                f.earnings_date = future[0].isoformat()
                f.earnings_days = (future[0] - today).days
        except Exception:  # noqa: BLE001 - calendar is best-effort
            pass

    # --- 52-week range ---
    f.week52_high = _num(info.get("fiftyTwoWeekHigh"))
    f.week52_low = _num(info.get("fiftyTwoWeekLow"))
    if f.week52_high and f.week52_low and px and f.week52_high > f.week52_low:
        f.pct_of_52w_range = (px - f.week52_low) / (f.week52_high - f.week52_low) * 100
        f.pct_from_high = (px / f.week52_high - 1.0) * 100

    # --- valuation / risk ---
    f.forward_pe = _num(info.get("forwardPE"))
    f.peg = _num(info.get("pegRatio") or info.get("trailingPegRatio"))
    f.revenue_growth = _num(info.get("revenueGrowth"))
    f.beta = _num(info.get("beta"))

    # --- short interest ---
    f.short_pct_float = _num(info.get("shortPercentOfFloat"))

    return f
