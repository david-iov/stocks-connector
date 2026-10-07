"""Offline tests for indicator and signal math (no network)."""

import numpy as np
import pandas as pd

from stocks import indicators as ind
from stocks.config import Config
from stocks.signals import evaluate


def _make_df(closes, volumes=None):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = pd.Series(closes, index=idx, dtype=float)
    vol = pd.Series(volumes if volumes is not None else [1_000_000] * n, index=idx, dtype=float)
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": vol}
    )


def test_rsi_all_gains_is_100():
    s = pd.Series(np.arange(1, 50, dtype=float))
    assert ind.rsi(s, 14).iloc[-1] == 100.0


def test_rsi_all_losses_is_zero():
    s = pd.Series(np.arange(50, 1, -1, dtype=float))
    assert ind.rsi(s, 14).iloc[-1] == 0.0


def test_sma_matches_manual_mean():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert ind.sma(s, 3).iloc[-1] == 4.0  # mean of 3,4,5


def test_uptrend_yields_bullish_call():
    closes = list(np.linspace(100, 160, 120))  # steady uptrend
    sig = evaluate("UP", _make_df(closes), Config())
    assert sig.composite > 0
    assert sig.action in ("BUY", "STRONG BUY")


def test_downtrend_yields_bearish_call():
    closes = list(np.linspace(160, 100, 120))  # steady downtrend
    sig = evaluate("DN", _make_df(closes), Config())
    assert sig.composite < 0
    assert sig.action in ("SELL", "STRONG SELL")


def test_insufficient_history_flags_error():
    sig = evaluate("SHORT", _make_df([100, 101, 102]), Config())
    assert sig.is_error


def test_returns_populated_for_windows():
    closes = list(np.linspace(100, 160, 120))
    sig = evaluate("UP", _make_df(closes), Config())
    assert set(sig.returns) >= {"1d", "7d", "30d"}
    # Steady uptrend -> every window should be positive.
    assert all(v > 0 for v in sig.returns.values())


def test_entry_advice_pullback_in_uptrend_is_good():
    # Long uptrend, then a modest dip at the end: trend intact, not overbought.
    closes = list(np.linspace(100, 160, 105)) + list(np.linspace(160, 150, 15))
    sig = evaluate("UP", _make_df(closes), Config())
    assert sig.entry_level == "good"


def test_entry_advice_downtrend_is_no():
    closes = list(np.linspace(160, 100, 120))
    sig = evaluate("DN", _make_df(closes), Config())
    assert sig.entry_level == "no"
    assert sig.entry.startswith("No")


def test_resolve_group_all_is_deduped_union():
    cfg = Config(groups={"a": ["AAPL", "MSFT"], "b": ["MSFT", "NVDA"]})
    assert cfg.resolve_group("all") == ["AAPL", "MSFT", "NVDA"]


def test_resolve_named_group():
    cfg = Config(groups={"quantum": ["IONQ", "RGTI"]})
    assert cfg.resolve_group("quantum") == ["IONQ", "RGTI"]


def test_resolve_unknown_group_raises():
    import pytest

    cfg = Config(groups={"core": ["AAPL"]})
    with pytest.raises(KeyError):
        cfg.resolve_group("nope")


if __name__ == "__main__":
    import sys
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
