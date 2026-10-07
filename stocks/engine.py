"""Shared orchestration: fetch + evaluate a whole watchlist."""

from __future__ import annotations

from .config import Config
from .data import fetch_history
from .signals import evaluate, action_rank, TickerSignal


def evaluate_watchlist(cfg: Config) -> list[TickerSignal]:
    """Fetch data and evaluate every ticker, ranked most-bullish first.

    Per-ticker fetch/parse failures are captured as error signals rather than
    aborting the whole run.
    """
    signals: list[TickerSignal] = []
    for ticker in cfg.watchlist:
        try:
            df = fetch_history(ticker, cfg.history_period, cfg.interval)
            signals.append(evaluate(ticker, df, cfg))
        except Exception as exc:  # noqa: BLE001 - surface any issue per-ticker
            signals.append(
                TickerSignal(
                    ticker=ticker, price=0.0, change_pct=0.0, rsi=float("nan"),
                    composite=0.0, action="HOLD", error=str(exc),
                )
            )

    signals.sort(key=lambda s: (action_rank(s.action), s.composite), reverse=True)
    return signals
