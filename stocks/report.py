"""Render evaluated signals as a terminal report."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box

from .signals import TickerSignal

_ACTION_STYLE = {
    "STRONG BUY": "bold green",
    "BUY": "green",
    "HOLD": "yellow",
    "SELL": "red",
    "STRONG SELL": "bold red",
}


_ENTRY_STYLE = {"good": "green", "wait": "yellow", "no": "red", "neutral": "dim"}
_ANALYST_STYLE = {"buy": "green", "hold": "yellow", "sell": "red", "none": "dim"}


def _fmt_ret(x: float | None) -> str:
    if x is None:
        return "[dim]–[/dim]"
    color = "green" if x > 0.05 else ("red" if x < -0.05 else "dim")
    return f"[{color}]{x:+.1f}%[/{color}]"


def render(signals: list[TickerSignal], console: Console | None = None) -> None:
    """Print a ranked signal table plus the reasoning behind each call."""
    console = console or Console()

    table = Table(
        title="Short-term signal report",
        box=box.SIMPLE_HEAVY,
        header_style="bold white",
    )
    table.add_column("Ticker", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("1D", justify="right")
    table.add_column("7D", justify="right")
    table.add_column("30D", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("Call")
    table.add_column("Analyst")
    table.add_column("Good to buy?")
    table.add_column("Why", style="dim", overflow="fold")

    ok = [s for s in signals if not s.is_error]
    errs = [s for s in signals if s.is_error]

    for s in ok:
        style = _ACTION_STYLE.get(s.action, "white")
        estyle = _ENTRY_STYLE.get(s.entry_level, "white")
        astyle = _ANALYST_STYLE.get(s.analyst_level, "dim")
        analyst = f"[{astyle}]{s.analyst_label}[/{astyle}]" if s.analyst_label else "[dim]–[/dim]"
        # Lead with the strongest-magnitude reasons.
        reasons = sorted(s.components, key=lambda c: abs(c.weighted), reverse=True)
        why = ", ".join(c.reason for c in reasons[:3])
        table.add_row(
            s.ticker,
            f"${s.price:,.2f}",
            _fmt_ret(s.returns.get("1d")),
            _fmt_ret(s.returns.get("7d")),
            _fmt_ret(s.returns.get("30d")),
            f"{s.rsi:.0f}",
            f"[{style}]{s.action}[/{style}]",
            analyst,
            f"[{estyle}]{s.entry}[/{estyle}]",
            why,
        )

    console.print(table)

    if errs:
        console.print("\n[dim]Skipped:[/dim]")
        for s in errs:
            console.print(f"  [red]{s.ticker}[/red]: {s.error}")

    console.print(
        "\n[dim italic]Educational signal output — not financial advice. "
        "Short-term technical signals are noisy; size positions and manage risk "
        "accordingly.[/dim italic]"
    )
