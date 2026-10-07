"""Market data retrieval via yfinance."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

# Yahoo caps how far back intraday data goes. Clamp the requested period to a
# safe max per interval so an over-long period doesn't silently return empty.
# (Values are a little under Yahoo's hard limits to stay safe.)
_INTRADAY_MAX_PERIOD = {
    "1m": "7d",
    "2m": "60d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "2y",
    "90m": "60d",
    "1h": "2y",
}


def _clamp_period(period: str, interval: str) -> str:
    """Return a period Yahoo will actually serve for the given interval."""
    return _INTRADAY_MAX_PERIOD.get(interval, period) if interval in _INTRADAY_MAX_PERIOD else period


def fetch_history(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Return an OHLCV DataFrame for one ticker, indexed by date/datetime.

    Columns are normalised to: Open, High, Low, Close, Volume. For intraday
    intervals the period is clamped to Yahoo's supported window (e.g. 15m data
    only goes back ~60 days), so an over-long config period still returns data.
    Raises ValueError if no data comes back (bad symbol, delisted, etc.).
    """
    safe_period = _clamp_period(period, interval)
    df = yf.download(
        ticker,
        period=safe_period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )

    if df is None or df.empty:
        raise ValueError(f"No data returned for {ticker!r}")

    # yfinance can hand back a MultiIndex even for a single ticker; flatten it.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if df.empty:
        raise ValueError(f"Only empty rows returned for {ticker!r}")

    return df
