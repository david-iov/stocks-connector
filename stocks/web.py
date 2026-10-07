"""Local web dashboard for the stocks connector.

Serves an auto-refreshing page of ranked short-term calls. Results are cached for
a short TTL so browser refreshes don't re-hit Yahoo on every poll.

Run:  python serve.py   (or  python -m stocks.web)
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, render_template_string

from .config import load_config, Config
from .engine import evaluate_watchlist

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"
# Cache longer when deployed: intraday bars only update every 15 min, and a
# longer TTL means fewer hits to Yahoo (which rate-limits cloud IPs).
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "90"))

app = Flask(__name__)

# Simple time-based cache guarded by a lock so concurrent requests don't all
# trigger a refetch at once.
_cache: dict = {"at": 0.0, "signals": None}
_lock = threading.Lock()
_config_path = str(DEFAULT_CONFIG)


def _load() -> Config:
    return load_config(_config_path)


def _get_signals(force: bool = False):
    now = time.time()
    with _lock:
        fresh = _cache["signals"] is not None and (now - _cache["at"]) < CACHE_TTL_SECONDS
        if fresh and not force:
            return _cache["signals"], _cache["at"]
        signals = evaluate_watchlist(_load())
        _cache["signals"] = signals
        _cache["at"] = now
        return signals, now


def _filter(signals, cfg: Config, group: str, max_price: float | None):
    """Filter the full result set by group membership and/or max price."""
    out = signals
    if group and group != "all":
        members = set(cfg.resolve_group(group))
        out = [s for s in out if s.ticker in members]
    if max_price is not None:
        out = [s for s in out if s.is_error or s.price <= max_price]
    return out


def _serialise(signals, updated_at):
    rows = []
    for s in signals:
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
        rows.append(d)
    return {"updated_at": updated_at, "rows": rows}


@app.route("/")
def index():
    groups = ["all", *_load().groups.keys()]
    return render_template_string(_PAGE, groups=groups)


@app.route("/api/signals")
def api_signals():
    from flask import request

    force = request.args.get("force") == "1"
    group = request.args.get("group", "all")
    raw_price = request.args.get("max_price")
    try:
        max_price = float(raw_price) if raw_price else None
    except ValueError:
        max_price = None

    cfg = _load()
    signals, updated_at = _get_signals(force=force)
    try:
        filtered = _filter(signals, cfg, group, max_price)
    except KeyError:
        filtered = signals
    return jsonify(_serialise(filtered, updated_at))


def main(host: str | None = None, port: int | None = None) -> None:
    # Honour the platform's PORT/HOST (Render, Railway, etc.); default to local.
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "5057"))
    print(f"Stocks dashboard → http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stocks connector</title>
<style>
  :root { color-scheme: dark; --bg:#0b0e14; --panel:#11151c; --line:#1f2630;
          --ink:#e6edf3; --dim:#8b949e; --green:#3fb950; --red:#f85149; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--ink); }
  header { display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
           padding: 18px 26px; border-bottom: 1px solid var(--line);
           position: sticky; top: 0; background: rgba(11,14,20,.92);
           backdrop-filter: blur(8px); z-index: 5; }
  h1 { font-size: 19px; margin: 0; font-weight: 700; letter-spacing: -.01em; }
  .breadth { font-size: 13px; color: var(--dim); display: flex; align-items: center; gap: 10px; }
  .breadth b { color: var(--ink); font-weight: 600; }
  .bar { width: 120px; height: 6px; border-radius: 3px; overflow: hidden;
         background: #30363d; display: inline-flex; }
  .bar > i { display: block; height: 100%; }
  .controls { margin-left: auto; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  button { background: #1b2230; color: var(--ink); border: 1px solid #2b3443;
           padding: 7px 13px; border-radius: 7px; cursor: pointer; font-size: 13px; }
  button:hover { background: #242d3d; }
  select, input[type=number] { background: #1b2230; color: var(--ink);
           border: 1px solid #2b3443; padding: 6px 9px; border-radius: 7px; font-size: 13px; }
  label.ctl { color: var(--dim); font-size: 13px; display: flex; gap: 6px; align-items: center; }
  main { padding: 18px 26px 56px; }
  .tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px;
               background: var(--panel); }
  table { border-collapse: collapse; width: 100%; min-width: 980px; }
  thead th { position: sticky; top: 0; background: var(--panel); z-index: 1; }
  th, td { text-align: left; padding: 11px 14px; border-bottom: 1px solid var(--line);
           white-space: nowrap; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: #151b24; }
  th { color: var(--dim); font-weight: 600; font-size: 11px; text-transform: uppercase;
       letter-spacing: .05em; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .ticker { font-weight: 700; font-size: 15px; }
  .price { font-variant-numeric: tabular-nums; }
  .ret { font-variant-numeric: tabular-nums; font-size: 13px; }
  .up { color: var(--green); } .down { color: var(--red); } .zero { color: var(--dim); }
  td.spark { padding: 6px 14px; width: 104px; } td.spark svg { display: block; }
  .call { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
  .pill { display: inline-block; padding: 3px 11px; border-radius: 999px;
          font-size: 11.5px; font-weight: 700; white-space: nowrap; letter-spacing: .02em; }
  .score { font-size: 11px; color: var(--dim); font-variant-numeric: tabular-nums; }
  .STRONGBUY { background: #0f2e1b; color: #45d268; border: 1px solid #1f6f3b; }
  .BUY       { background: #0f2419; color: #45d268; }
  .HOLD      { background: #2a2410; color: #d7a422; }
  .SELL      { background: #2a1416; color: #f17b74; }
  .STRONGSELL{ background: #2a1416; color: #f17b74; border: 1px solid #a33; }
  .entry { display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px;
           border-radius: 8px; font-size: 12.5px; font-weight: 600; }
  .entry small { display: block; font-weight: 400; font-size: 11px; color: var(--dim);
                 margin-top: 2px; white-space: normal; max-width: 180px; }
  .entrywrap { display: flex; flex-direction: column; gap: 2px; }
  .e-good { background: #0f2419; color: #56d364; }
  .e-wait { background: #2a2410; color: #d7a422; }
  .e-no   { background: #2a1416; color: #f17b74; }
  .e-neutral { background: #1c2128; color: var(--dim); }
  .factors { display: flex; flex-wrap: wrap; gap: 5px; max-width: 440px; white-space: normal; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
          border-radius: 999px; font-size: 12px; border: 1px solid transparent; }
  .chip .ar { font-size: 10px; }
  .chip.bull { background: #11261a; color: #56d364; border-color: #1a3b26; }
  .chip.bear { background: #2a1416; color: #f17b74; border-color: #42191c; }
  .chip.flat { background: #1c2128; color: var(--dim); border-color: #2a2f37; }
  .err { color: var(--dim); font-style: italic; }
  .legend { color: var(--dim); font-size: 12.5px; display: flex; align-items: center;
            gap: 14px; flex-wrap: wrap; margin: 0 0 12px; }
  .legend .grp { display: flex; align-items: center; gap: 6px; }
  .disclaimer { color: #6e7681; font-size: 12px; margin-top: 22px; max-width: 820px; }
  .spin { opacity: .45; transition: opacity .2s; }
</style>
</head>
<body>
<header>
  <h1>📈 Stocks connector</h1>
  <div class="breadth" id="breadth">loading…</div>
  <div class="controls">
    <label class="ctl">Group
      <select id="group">
        {% for g in groups %}<option value="{{ g }}">{{ g }}</option>{% endfor %}
      </select>
    </label>
    <label class="ctl">Max $
      <input type="number" id="maxprice" min="0" step="1" placeholder="any" style="width:72px">
    </label>
    <label class="ctl"><input type="checkbox" id="auto" checked> auto</label>
    <button id="refresh">↻ Refresh</button>
  </div>
</header>
<main>
  <div class="legend">
    <span class="grp">Drivers:
      <span class="chip bull"><span class="ar">▲</span>bullish</span>
      <span class="chip bear"><span class="ar">▼</span>bearish</span>
      <span class="chip flat"><span class="ar">•</span>neutral</span></span>
    <span class="grp">Good to buy?:
      <span class="entry e-good">Yes</span>
      <span class="entry e-wait">Wait</span>
      <span class="entry e-no">No</span></span>
    <span>Returns are price change over 1 / 7 / 30 calendar days.</span>
  </div>
  <div class="tablewrap">
  <table>
    <thead><tr>
      <th>Ticker</th><th class="num">Price</th>
      <th class="num">1D</th><th class="num">7D</th><th class="num">30D</th>
      <th>Trend</th><th>Signal</th><th>Good to buy?</th><th>What's driving it</th>
    </tr></thead>
    <tbody id="rows"><tr><td colspan="9">Fetching market data…</td></tr></tbody>
  </table>
  </div>
  <p class="disclaimer">Educational signal output — <b>not financial advice</b>.
  "Good to buy?" is a short-term technical entry read, not a recommendation; signals
  are noisy and backward-looking. Do your own research and manage risk.</p>
</main>
<script>
  const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString();
  const pillClass = a => a.replace(/\\s+/g, '');
  function retCell(v) {
    if (v === undefined || v === null || isNaN(v)) return '<td class="num ret zero">–</td>';
    const cls = v > 0.05 ? 'up' : (v < -0.05 ? 'down' : 'zero');
    const sign = v > 0 ? '+' : '';
    return `<td class="num ret ${cls}">${sign}${v.toFixed(1)}%</td>`;
  }
  function spark(values) {
    if (!values || values.length < 2) return '';
    const w = 100, h = 28, pad = 3;
    const min = Math.min(...values), max = Math.max(...values);
    const span = (max - min) || 1;
    const pts = values.map((v, i) => {
      const x = pad + i * (w - 2 * pad) / (values.length - 1);
      const y = pad + (h - 2 * pad) * (1 - (v - min) / span);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const up = values[values.length - 1] >= values[0];
    const color = up ? '#3fb950' : '#f85149';
    const last = pts.split(' ').pop().split(',');
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <polyline fill="none" stroke="${color}" stroke-width="1.5"
        stroke-linejoin="round" stroke-linecap="round" points="${pts}"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="2" fill="${color}"/>
    </svg>`;
  }
  function chips(factors) {
    const T = 0.3;  // mild leans stay neutral/gray so colour matches the wording
    return '<div class="factors">' + factors.map(f => {
      const cls = f.score > T ? 'bull' : (f.score < -T ? 'bear' : 'flat');
      const ar = f.score > T ? '▲' : (f.score < -T ? '▼' : '•');
      return `<span class="chip ${cls}"><span class="ar">${ar}</span>${f.reason}</span>`;
    }).join('') + '</div>';
  }
  function row(r) {
    if (r.error) {
      return `<tr><td class="ticker">${r.ticker}</td>
        <td colspan="8" class="err">${r.why}</td></tr>`;
    }
    const ret = r.returns || {};
    return `<tr>
      <td class="ticker">${r.ticker}</td>
      <td class="num price">$${r.price.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      ${retCell(ret['1d'])}${retCell(ret['7d'])}${retCell(ret['30d'])}
      <td class="spark">${spark(r.spark)}</td>
      <td><div class="call"><span class="pill ${pillClass(r.action)}">${r.action}</span>
        <span class="score">score ${r.composite >= 0 ? '+' : ''}${r.composite.toFixed(2)} · RSI ${isNaN(r.rsi)?'–':r.rsi.toFixed(0)}</span></div></td>
      <td><div class="entrywrap"><span class="entry e-${r.entry_level}">${r.entry}</span>
        <small>${r.entry_note}</small></div></td>
      <td>${chips(r.factors)}</td>
    </tr>`;
  }
  function renderBreadth(rows, updated_at) {
    const priced = rows.filter(r => !r.error && r.returns && r.returns['1d'] !== undefined);
    const down = priced.filter(r => r.returns['1d'] < 0).length;
    const upN = priced.filter(r => r.returns['1d'] > 0).length;
    const n = priced.length || 1;
    const buys = rows.filter(r => !r.error && r.entry_level === 'good').length;
    const pctDown = Math.round(100 * down / n);
    const tone = down > upN ? 'down' : (upN > down ? 'up' : 'zero');
    document.getElementById('breadth').innerHTML =
      `<span class="bar"><i style="width:${100-pctDown}%;background:var(--green)"></i>` +
      `<i style="width:${pctDown}%;background:var(--red)"></i></span>` +
      `<span class="${tone}"><b>${down}/${n}</b> down today</span>` +
      `<span>· <b>${buys}</b> flagged buyable</span>` +
      `<span>· updated ${fmtTime(updated_at)}</span>`;
  }
  async function load(force) {
    const params = new URLSearchParams();
    if (force) params.set('force', '1');
    params.set('group', document.getElementById('group').value);
    const mp = document.getElementById('maxprice').value;
    if (mp) params.set('max_price', mp);
    document.querySelector('table').classList.add('spin');
    try {
      const res = await fetch('/api/signals?' + params.toString());
      const data = await res.json();
      document.getElementById('rows').innerHTML = data.rows.map(row).join('') ||
        '<tr><td colspan="9" class="err">No stocks match this filter.</td></tr>';
      renderBreadth(data.rows, data.updated_at);
    } catch (e) {
      document.getElementById('breadth').textContent = 'error loading signals';
    } finally {
      document.querySelector('table').classList.remove('spin');
    }
  }
  document.getElementById('refresh').onclick = () => load(true);
  document.getElementById('group').onchange = () => load(false);
  document.getElementById('maxprice').oninput = () => load(false);
  let timer = setInterval(() => { if (document.getElementById('auto').checked) load(false); }, 60000);
  load(false);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
