"""Command-line entry point for the stocks connector."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .config import load_config
from .engine import evaluate_watchlist
from . import report

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stocks",
        description="Watch a list of tickers and advise on short-term entries.",
    )
    parser.add_argument(
        "-c", "--config", default=str(DEFAULT_CONFIG),
        help="Path to config.yaml (default: project config.yaml).",
    )
    parser.add_argument(
        "-t", "--tickers", nargs="+", metavar="SYM",
        help="Override the watchlist with these symbols for this run.",
    )
    parser.add_argument(
        "-g", "--group", metavar="NAME",
        help="Scan a named group from config (e.g. core, quantum, all).",
    )
    parser.add_argument(
        "--max-price", type=float, metavar="N",
        help="Only show stocks trading at or below $N (cheap 'fast mover' screen).",
    )
    parser.add_argument(
        "--period", help="Override history period (e.g. 3mo, 6mo, 1y).",
    )
    parser.add_argument(
        "--interval", help="Override bar interval (e.g. 1d, 1h, 30m).",
    )
    parser.add_argument(
        "--only-actionable", action="store_true",
        help="Show only BUY/SELL calls, hiding HOLDs.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()

    cfg = load_config(args.config)
    # Precedence: explicit tickers > named group > config default.
    if args.tickers:
        cfg.watchlist = [t.upper() for t in args.tickers]
    elif args.group:
        try:
            cfg.watchlist = cfg.resolve_group(args.group)
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
    if args.period:
        cfg.history_period = args.period
    if args.interval:
        cfg.interval = args.interval

    if not cfg.watchlist:
        console.print("[red]No tickers to watch.[/red] Add some to config.yaml or pass -t.")
        return 1

    with console.status("[bold]Fetching market data…[/bold]"):
        signals = evaluate_watchlist(cfg)

    if args.max_price is not None:
        # Keep errored tickers so the user still sees what failed to price.
        signals = [s for s in signals if s.is_error or s.price <= args.max_price]

    if args.only_actionable:
        signals = [s for s in signals if s.action not in ("HOLD",) or s.is_error]

    report.render(signals, console)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
