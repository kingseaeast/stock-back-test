# Stock Strategy Backtester

A personal tool for backtesting simple, long-term stock strategies on daily price
data. The engine runs locally; reports are self-contained HTML files committed to
this repo and published via **GitHub Pages**.

See [`PRD.md`](PRD.md) for product scope, [`ENG_DESIGN.md`](ENG_DESIGN.md) for
architecture, and [`PLAN.md`](PLAN.md) for the milestone plan.

## How it works

```
  describe a strategy in chat
            │
            ▼
  AI agent runs:  python -m src.cli run ...
            │
            ▼
  Local engine  →  docs/runs/<id>.html  +  docs/runs.json entry
            │
            ▼
  git push     →  GitHub Pages serves the dashboard at
                  https://<user>.github.io/<repo>/
```

No backend, no hosted LLM, no API keys in the repo.

## Setup

Requires `uv` and Python 3.12.

```sh
uv sync
```

Daily prices are fetched via `yfinance` and cached to `data/prices/` (gitignored).

## Running a backtest

### Via the AI agent (preferred)

Describe what you want in natural language in your coding-agent session and let
it invoke the CLI. Example prompts:

- "Backtest monthly DCA on SPY from 2015 to today with a $12,000 budget."
- "Compare buy-and-hold vs DCA on QQQ over the last 5 years."

### Via the CLI directly

```sh
uv run python -m src.cli list-strategies

uv run python -m src.cli run \
  --strategy dca \
  --ticker SPY \
  --start 2015-01-01 \
  --end 2024-12-31 \
  --budget 12000 \
  --params '{"cadence":"monthly"}'
```

Each run writes:
- `docs/runs/<timestamp>_<strategy>_<ticker>.html` — a self-contained Plotly report
- a new entry appended to `docs/runs.json`

Open `docs/index.html` locally, or push to GitHub and view via Pages.

## Strategies

| Name | Description | Key params |
| --- | --- | --- |
| `buy_hold` | Deploy entire `--budget` on day one and hold. | — |
| `dca` | Split `--budget` into equal contributions on a cadence (`weekly`, `biweekly`, `monthly`). | `cadence` |
| `dca_btd` | DCA most of the budget, hold back a reserve to buy on N-day drawdowns. | `cadence`, `dip_reserve_pct`, `dip_threshold_pct`, `dip_lookback`, `dip_buys` |
| `dca_fg` | DCA most of the budget, hold back a reserve to buy on CNN Fear & Greed dips into extreme fear. | `cadence`, `fear_reserve_pct`, `fear_threshold`, `fear_buys`, `index_type` |
| `rsi` | All-in / all-out on Wilder RSI thresholds. Starts invested (or pass `start_in_cash`). | `period`, `oversold`, `overbought`, `start_in_cash` |
| `fear_greed` | All-in / all-out on the CNN Fear & Greed index. Starts in cash by default. Two data sources: `--fg-source cnn` (default, ~5.5y, includes sub-indices) or `--fg-source whit3rabbit` (~15y back to 2011, headline score only — community mirror, no license). | `buy_below`, `exit_above`, `index_type`, `start_in_market` |

Every run compares against **both** `buy_hold` and `dca_monthly` benchmarks on
the same ticker, window, and budget (when not redundant with the strategy
itself).

## Tests

```sh
uv run pytest                    # 81 unit tests, fully offline, ~0.3s
uv run pytest -m integration     # parity check (Python vs browser JS); needs Node
uv run pytest -m ""              # all tests
```

The integration suite runs every committed report through both engines
(`src/engine.py` and `docs/engine.js`) and fails if any metric diverges past
tolerance. Parameterized one test per report so failures point at the exact
file + metric. See [`scripts/README.md`](scripts/README.md) for the
standalone script.

## Conventions

- Idle cash earns 0% in this model. Reports state this in the header.
- Orders dated `D` execute at trading day `D+1` adjusted close (no look-ahead).
- Commission and slippage default to 5 bps each; override via `--commission-bps` / `--slippage-bps`.
- Reports are immutable once committed. To revise, re-run and commit a new file.

## Publishing to GitHub Pages

One-time setup after you push the repo to GitHub:

1. **Settings → Pages → Source:** Deploy from branch.
2. **Branch:** `main`, **folder:** `/docs`. Save.
3. Wait ~1 minute. Your dashboard is live at `https://<user>.github.io/<repo>/`.

After that, every push to `main` is a deploy.

## Layout

```
src/
  data/prices.py        yfinance loader + Parquet cache
  strategies/           buy_hold, dca, base protocol
  engine.py             order-schedule simulator
  metrics.py            CAGR, total return, max DD, ...
  report.py             Result → self-contained HTML
  manifest.py           append to docs/runs.json
  cli.py                `python -m src.cli`
docs/
  index.html / app.js / style.css   the dashboard
  runs.json             manifest of every backtest
  runs/                 one HTML per backtest
```
