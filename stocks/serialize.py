"""Shared serialization: turn a TickerSignal into a JSON-ready dict.

Used by both the live Flask server (web.py) and the static site builder
(build_static.py) so the row shape stays identical across both.
"""

from __future__ import annotations

from dataclasses import asdict

from .signals import TickerSignal


def signal_to_row(s: TickerSignal) -> dict:
    """One ranked row: price, returns, call, entry advice, and factor chips."""
    d = asdict(s)
    if s.is_error:
        d["factors"] = []
        d["why"] = s.error
    else:
        # Each factor keeps its signed score so the UI can colour by direction.
        # Strongest-magnitude drivers first.
        ordered = sorted(s.components, key=lambda c: abs(c.weighted), reverse=True)
        d["factors"] = [{"reason": c.reason, "score": round(c.score, 3)} for c in ordered]
        d["why"] = "; ".join(c.reason for c in ordered[:3])
    # The raw component dataclasses aren't needed client-side; drop to keep JSON small.
    d.pop("components", None)
    return d
