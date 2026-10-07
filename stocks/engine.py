"""Shared orchestration: fetch + evaluate a whole watchlist."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone

from .config import Config
from .data import fetch_history
from .fundamentals import fetch_fundamentals
from .signals import evaluate, action_rank, TickerSignal
from .serialize import signal_to_row


def evaluate_watchlist(cfg: Config, with_fundamentals: bool = True) -> list[TickerSignal]:
    """Fetch data and evaluate every ticker, ranked most-bullish first.

    For each ticker we pull price history plus (optionally) a fundamentals blob
    (analyst targets, earnings date, valuation). Both are best-effort: a
    fundamentals failure still yields a technicals-only row, and a price-history
    failure is captured as an error signal rather than aborting the whole run.
    """
    signals: list[TickerSignal] = []
    for ticker in cfg.watchlist:
        try:
            df = fetch_history(ticker, cfg.history_period, cfg.interval)
            fund = None
            if with_fundamentals:
                price = float(df["Close"].iloc[-1])
                fund = fetch_fundamentals(ticker, price)  # never raises
            signals.append(evaluate(ticker, df, cfg, fund))
        except Exception as exc:  # noqa: BLE001 - surface any issue per-ticker
            signals.append(
                TickerSignal(
                    ticker=ticker, price=0.0, change_pct=0.0, rsi=float("nan"),
                    composite=0.0, action="HOLD", error=str(exc),
                )
            )

    signals.sort(key=lambda s: (action_rank(s.action), s.composite), reverse=True)
    return signals


def build_dataset(cfg: Config, with_fundamentals: bool = True) -> dict:
    """Evaluate the union of all groups and return the JSON payload the UI reads.

    Shared by the static site builder and the live server so both serve an
    identical shape: {updated_at, generated_utc, interval, groups, rows}.
    """
    watchlist = cfg.resolve_group("all") if cfg.groups else cfg.watchlist
    scan = replace(cfg, watchlist=watchlist)
    signals = evaluate_watchlist(scan, with_fundamentals=with_fundamentals)
    return {
        "updated_at": time.time(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "interval": cfg.interval,
        "groups": cfg.groups,
        "rows": [signal_to_row(s) for s in signals],
    }
