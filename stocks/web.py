"""Local/live web dashboard for the stocks connector.

Serves the same static page as the GitHub Pages site (docs/index.html) plus a
`/signals.json` endpoint built on demand. Results are cached for a short TTL so
refreshes don't re-hit Yahoo on every request.

Run:  python serve.py   (or  python -m stocks.web)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .config import load_config, Config
from .engine import build_dataset

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
DOCS = ROOT / "docs"
# Cache longer when deployed: intraday bars only update every 15 min, and a
# longer TTL means fewer hits to Yahoo (which rate-limits cloud IPs).
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "90"))

app = Flask(__name__)

# Time-based cache guarded by a lock so concurrent requests don't all refetch.
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _dataset(force: bool = False) -> dict:
    now = time.time()
    with _lock:
        fresh = _cache["data"] is not None and (now - _cache["at"]) < CACHE_TTL_SECONDS
        if fresh and not force:
            return _cache["data"]
        data = build_dataset(load_config(DEFAULT_CONFIG))
        _cache["data"] = data
        _cache["at"] = now
        return data


@app.route("/")
def index():
    return send_from_directory(DOCS, "index.html")


@app.route("/signals.json")
def signals_json():
    from flask import request

    force = request.args.get("force") == "1"
    return jsonify(_dataset(force=force))


def main(host: str | None = None, port: int | None = None) -> None:
    # Honour the platform's PORT/HOST (Render, Railway, etc.); default to local.
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "5057"))
    print(f"Stocks dashboard → http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
