# Stocks connector

A CLI that watches a list of tickers and advises on **short-term** entries using
classic technical-momentum signals. It pulls daily (or intraday) market data from
Yahoo Finance, computes a handful of indicators, blends them into a single
composite score, and prints a ranked BUY/HOLD/SELL report with the reasoning
behind each call.

> ⚠️ **Not financial advice.** This is an educational tool. Short-term technical
> signals are noisy and backward-looking. Do your own research and manage risk.

## Signals

For each ticker the connector computes five components, each normalised to
`[-1, 1]`, then weighted and summed into a composite score:

| Component  | What it measures                                             |
|------------|--------------------------------------------------------------|
| `rsi`      | RSI(14) — oversold is bullish, overbought is bearish         |
| `macd`     | MACD histogram + fresh bullish/bearish crossovers            |
| `ma_cross` | Fast vs slow SMA separation + golden/death crosses           |
| `trend`    | Price distance above/below the fast SMA (momentum)           |
| `volume`   | Volume spike confirming the direction of the latest move     |

The composite score maps to an action via thresholds in `config.yaml`:
`STRONG BUY / BUY / HOLD / SELL / STRONG SELL`.

## Setup

Requires Python 3.9+ (3.13 recommended).

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Usage

```bash
# Run the watchlist defined in config.yaml
.venv/bin/python main.py

# Ad-hoc tickers for one run
.venv/bin/python main.py -t AAPL NVDA SPY

# Scan a named group from config (core, quantum, all)
.venv/bin/python main.py -g quantum

# Screen for low-priced "fast mover" names (<= $20)
.venv/bin/python main.py --max-price 20

# Combine: cheap quantum names, actionable only
.venv/bin/python main.py -g quantum --max-price 20 --only-actionable

# Override history window / bar size
.venv/bin/python main.py --period 3mo --interval 1d
```

Flags: `-c/--config`, `-t/--tickers`, `-g/--group`, `--max-price`, `--period`,
`--interval`, `--only-actionable`.

### Watchlist groups

`config.yaml` organises tickers into named groups under `watchlists:`. Two ship
by default:

- **core** — large-cap momentum names.
- **quantum** — quantum-computing pure-plays (IONQ, RGTI, QBTS, QUBT, ARQQ,
  LAES) plus the QTUM ETF as a basket benchmark. Mostly low-priced, high-beta
  small caps — fast movers, high risk. (QMCO is Quantum *Corp* — storage, not
  quantum computing — included by request and labeled as such.)
- **tech** — broader tech: semis (AVGO, TSM, ASML, MU, QCOM, INTC, ARM, SMCI,
  MRVL), software & platforms (PLTR, CRM, ADBE, NFLX, CRWD, PANW, NET, SNOW,
  SHOP, UBER, COIN).

Pick one with `-g NAME`, or use `all` (the default) to scan every group. Add your
own groups by editing `watchlists:` in `config.yaml`.

> **On "easy to double" / low-priced stocks:** a low share price doesn't make a
> double more likely on its own — that's driven by volatility and catalysts, not
> the dollar price. `--max-price` is a convenience screen for fast-moving small
> caps, which swing hard in *both* directions. Size positions accordingly.

## Web dashboard

For a leave-a-tab-open view, run the local dashboard:

```bash
.venv/bin/python serve.py
# → http://127.0.0.1:5057
```

An auto-refreshing page shows the ranked calls with, per row:

- **Price** and **1D / 7D / 30D** returns (price change over 1, 7, 30 calendar
  days), color-coded green/red.
- A **Trend sparkline** (green if the last close is above the window's first).
- **Signal** — the BUY/SELL pill with its composite score and RSI underneath.
- **Good to buy?** — a short-term *entry-timing* read, distinct from the overall
  call: `Yes — dip buy` (pullback within an uptrend), `Buyable`, `Wait —
  overbought`, or `No — downtrend`, each with a one-line rationale.
- **What's driving it** — color-coded factor chips (green bullish, red bearish,
  gray neutral) so you can see which signals push the score up vs down.

The header shows **market breadth** — how many names are down today and how many
are flagged buyable. A **group** dropdown (core / quantum / tech / all)
and a **max $** box let you filter live — e.g. pick `quantum` and set max $ to 10
to see only cheap quantum names. It uses the same config as the CLI. Signals are
cached for 90s server-side, so browser refreshes won't re-hit Yahoo on every
poll; the page auto-polls every 60s (toggle off with the checkbox) and "Refresh
now" forces a fresh fetch.

## Data & freshness

Data comes from **Yahoo Finance via the `yfinance` library** (free, no API key).
It is **not a real-time feed** — Yahoo is delayed ~15 min for US equities. The
default interval is **15-minute bars** (`config.yaml`), auto-clamped to Yahoo's
~60-day intraday limit. Indicators are computed on those bars, so on 15m data
"RSI(14)" is a 14-bar (~3.5h) intraday reading. This is a short-term swing view,
not an intraday day-trading feed. For end-of-day signals instead, set
`interval: 1d` and `history_period: 6mo`.

## Deploying (free, no credit card — GitHub Pages)

The primary hosted setup needs **no server and no card**: a scheduled GitHub
Action rebuilds the data, and GitHub Pages serves a static dashboard.

How it works:
- `build_static.py` evaluates every group once and writes `docs/signals.json`.
- `docs/index.html` is a static, **mobile-friendly** page that fetches that JSON
  and filters by group / price **client-side** — no backend.
- `.github/workflows/update.yml` runs `build_static.py` on a cron (every 15 min
  during US market hours) and commits the refreshed `signals.json`.

One-time setup:
1. In the repo: **Settings → Pages → Build and deployment → Source: Deploy from a
   branch**, pick `main` and the **`/docs`** folder, Save.
2. The site appears at `https://<user>.github.io/<repo>/` within a minute.
3. (Optional) Actions tab → **Refresh signals → Run workflow** to populate data
   immediately instead of waiting for the next cron tick.

Tradeoff: the dashboard shows the **last cron snapshot** (≤15 min old), not an
on-demand fetch. Fetching runs on GitHub's infrastructure, which sidesteps the
serverless timeouts and keeps your machine out of it.

### Alternative: a live server (Render / Railway / Fly)

For an on-demand live app instead of snapshots, the Flask server also deploys to
any "web service" host via the included `render.yaml` / `Procfile` (start command
`gunicorn stocks.web:app`, reads `$PORT` and `$CACHE_TTL_SECONDS`). Note most of
these now **require a card on file** even on their free tiers, and Yahoo may
rate-limit cloud IPs — per-ticker failures degrade gracefully, but a hosted
instance can be flakier than local. Swap to a keyed provider (Finnhub/Polygon) if
that bites.

## Configuration

Edit `config.yaml` to change the watchlist, indicator parameters, component
weights, and action thresholds. Each section is documented inline.

## Scheduling

To get a report on a schedule, drop a cron entry pointing at the venv Python:

```cron
# Weekdays at 9:45am ET, after the open
45 9 * * 1-5  cd /path/to/stocks && .venv/bin/python main.py --only-actionable >> report.log 2>&1
```

## Project layout

```
config.yaml          # watchlist + tunable parameters
render.yaml          # live-server deploy blueprint (optional)
Procfile             # start command for web-service hosts (optional)
build_static.py      # writes docs/signals.json for the static site
main.py              # CLI entry point (python main.py)
serve.py             # live dashboard entry point (python serve.py)
docs/                # GitHub Pages site (static)
  index.html         # mobile-friendly dashboard, reads signals.json
  signals.json       # generated data (committed by the Action)
.github/workflows/
  update.yml         # cron: rebuild signals.json every ~15 min
stocks/
  config.py          # typed config loading
  data.py            # yfinance data fetch (intraday-period clamping)
  indicators.py      # RSI / MACD / SMA / EMA
  signals.py         # component scores, returns, entry advice, composite call
  engine.py          # fetch + evaluate the whole watchlist (shared)
  serialize.py       # TickerSignal -> JSON row (shared by web + builder)
  report.py          # rich terminal report
  cli.py             # argument parsing + orchestration
  web.py             # Flask dashboard (page + /api/signals)
tests/
  test_signals.py    # offline indicator/signal tests
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```
