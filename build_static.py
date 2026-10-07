#!/usr/bin/env python3
"""Build the static dashboard data: evaluate every group, write docs/signals.json.

Run by the GitHub Action on a schedule (and locally for testing). The committed
docs/index.html reads this JSON and filters client-side, so GitHub Pages can
serve the whole dashboard with no server.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from stocks.config import load_config
from stocks.engine import evaluate_watchlist
from stocks.serialize import signal_to_row

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def build() -> dict:
    cfg = load_config(ROOT / "config.yaml")

    # Evaluate the union of every group once; the client filters by group.
    cfg.watchlist = cfg.resolve_group("all")
    signals = evaluate_watchlist(cfg)

    now = time.time()
    return {
        "updated_at": now,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "interval": cfg.interval,
        "groups": cfg.groups,
        "rows": [signal_to_row(s) for s in signals],
    }


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    data = build()
    out = DOCS / "signals.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    ok = sum(1 for r in data["rows"] if not r.get("error"))
    print(f"Wrote {out} — {ok}/{len(data['rows'])} tickers priced, interval {data['interval']}")


if __name__ == "__main__":
    main()
