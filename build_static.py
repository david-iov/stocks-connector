#!/usr/bin/env python3
"""Build the static dashboard data: evaluate every group, write docs/signals.json.

Run by the GitHub Action on a schedule (and locally for testing). The committed
docs/index.html reads this JSON and filters client-side, so GitHub Pages can
serve the whole dashboard with no server.
"""

from __future__ import annotations

import json
from pathlib import Path

from stocks.config import load_config
from stocks.engine import build_dataset

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    cfg = load_config(ROOT / "config.yaml")
    data = build_dataset(cfg)
    out = DOCS / "signals.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    ok = sum(1 for r in data["rows"] if not r.get("error"))
    print(f"Wrote {out} — {ok}/{len(data['rows'])} tickers priced, interval {data['interval']}")


if __name__ == "__main__":
    main()
