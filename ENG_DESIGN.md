# Engineering Design — Stock Strategy Backtester

## 1. Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│  Local machine (developer)                                   │
│                                                              │
│   AI agent (Claude Code)                                     │
│        │                                                     │
│        ▼                                                     │
│   src/backtest.py  ──►  yfinance ──►  data/*.parquet (cache)│
│        │                                                     │
│        ▼                                                     │
│   Plotly HTML  ──►  docs/runs/<ts>_<strategy>_<ticker>.html │
│   Manifest    ──►   docs/runs.json (append)                 │
└─────────────────────────────────────────────────────────────┘
                              │ git push
                              ▼
                ┌──────────────────────────────┐
                │  GitHub Pages (serves /docs) │
                │                              │
                │  index.html  (dashboard)     │
                │  app.js      (filters/list)  │
                │  runs.json   (manifest)      │
                │  runs/*.html (reports)       │
                └──────────────────────────────┘
```

No server runs anywhere. The site is fully static. The "AI" is the user's local coding agent — it is not called from the deployed site.

## 2. Repository Layout

```
.
├── PRD.md
├── ENG_DESIGN.md
├── PLAN.md
├── README.md                    # how to run the agent + publish
├── pyproject.toml               # uv-managed; deps: vectorbt, yfinance, plotly, pandas
├── .python-version
├── .gitignore                   # data/, __pycache__/, .venv/
├── data/                        # local cache (gitignored)
│   ├── prices/<ticker>.parquet
│   └── fear_greed.parquet
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── prices.py            # yfinance fetch + cache
│   │   └── fear_greed.py        # CNN F&G endpoint fetch + cache
│   ├── strategies/
│   │   ├── __init__.py          # registry
│   │   ├── base.py              # Strategy protocol
│   │   ├── buy_hold.py
│   │   ├── dca.py               # always also runs as benchmark
│   │   ├── dca_btd.py           # DCA + buy-the-dip reserve
│   │   ├── rsi.py               # all-in / all-out on RSI thresholds
│   │   └── fear_greed.py        # all-in / all-out on CNN F&G thresholds
│   ├── engine.py                # run_backtest(strategy, ticker, period, params) -> Result
│   ├── metrics.py               # CAGR, Sharpe, Sortino, max DD, win rate, exposure
│   ├── report.py                # Result -> standalone HTML via Plotly
│   ├── manifest.py              # append entry to docs/runs.json
│   └── cli.py                   # `python -m src.cli run ...` thin wrapper
├── tests/
│   ├── test_metrics.py
│   ├── test_strategies.py       # golden tests with synthetic prices
│   └── test_manifest.py
└── docs/
    ├── index.html               # dashboard shell
    ├── app.js                   # loads runs.json, renders table + filters
    ├── style.css
    ├── runs.json                # [] initially
    └── runs/                    # one HTML per backtest
```

## 3. Core Data Types

```python
# src/strategies/base.py
class Strategy(Protocol):
    name: str                                       # "ma_crossover"
    def signals(self, prices: pd.DataFrame, **params) -> pd.Series:
        """Return a Series of {-1, 0, 1} aligned to prices.index.
        +1 = enter long, -1 = exit, 0 = hold."""
```

```python
# src/engine.py
@dataclass(frozen=True)
class RunConfig:
    strategy: str            # registry key
    ticker: str
    start: date
    end: date
    params: dict[str, Any]
    total_budget: float = 10_000      # same dollars across strategy + both benchmarks
    commission_bps: float = 5
    slippage_bps: float = 5

@dataclass(frozen=True)
class StrategyRun:
    name: str                          # "rsi", "buy_hold", "dca_monthly", ...
    equity: pd.Series                  # portfolio value (invested + idle cash) by date
    cash_deployed: pd.Series           # cumulative dollars actually put to work
    trades: pd.DataFrame               # date, side, qty, price, notional
    metrics: dict[str, float]          # CAGR, sharpe, sortino, max_dd, n_buys, n_sells, exposure, final_value

@dataclass(frozen=True)
class Result:
    config: RunConfig
    strategy: StrategyRun              # the user-requested strategy
    benchmarks: list[StrategyRun]      # always [buy_hold, dca_monthly]
    run_id: str                        # YYYYMMDD-HHMMSS-<slug>
```

Final value, not just CAGR, is the headline number because DCA strategies don't deploy capital all at once — CAGR alone misrepresents them.

## 4. Module Responsibilities

### `data/prices.py`
- `load_prices(ticker, start, end) -> pd.DataFrame` with columns `[open, high, low, close, adj_close, volume]`, indexed by date.
- Cache to `data/prices/<ticker>.parquet`. On request, fetch only the missing tail and merge.
- Use **adjusted close** for all strategy and metric calculations.

### `data/fear_greed.py`
- `load_fear_greed(start, end) -> pd.DataFrame` with columns `[fear_greed, momentum, strength, breadth, put_call, junk_demand, volatility, safe_haven]` indexed by date (one column per CNN sub-index; main index in `fear_greed`).
- Source: `https://production.dataviz.cnn.io/index/fearandgreed/graphdata` (unofficial; user-agent header required).
- Cache to `data/fear_greed.parquet`. Single shared file — F&G is not per-ticker.
- History limit: CNN serves roughly the last 3 years. The fetcher raises a clear error if the requested `start` predates available data; the engine surfaces this to the user/agent.
- If the endpoint changes/breaks, this is the only file that needs updating; the adapter interface stays the same.

### `strategies/`
- Each strategy lives in its own file; registered in `strategies/__init__.py` via a `REGISTRY: dict[str, type[Strategy]]`.
- Price-only strategies are pure functions of prices + params → signals. No I/O, no state.
- The F&G strategy takes a second input series (the F&G index) alongside prices. To keep the `Strategy` protocol uniform, strategies declare what extra data they need via a `data_requirements` class attribute (`{"prices", "fear_greed"}`); the engine loads and aligns those before calling `signals(...)`.
- All series are aligned to the prices' trading-day index; F&G readings on non-trading days are forward-filled to the next session, and the joined frame is trimmed to the intersection of available history.
- Tested with synthetic series for deterministic golden values.

### `engine.py`
- Orchestrates: load prices (+ F&G if needed) → call strategy to produce an **order schedule** (date → action) → run a small custom simulator → extract equity, cash deployed, trades.
- **Why custom simulator, not vectorbt for v1:** our model mixes DCA contributions (cash injected over time) with all-in/all-out signal strategies; vectorbt can do this but the API gets gnarly. ~80 lines of pure Python is more transparent and easier to test for v1. `vectorbt` stays in deps as a future option for parameter sweeps/heatmaps.
- Applies commission and slippage uniformly.
- Always computes **two benchmarks** (`buy_hold` and `dca_monthly`) on the same ticker/window/budget.
- Strategies emit order schedules rather than ±1 signals so DCA-style contributions and all-in/all-out signals share one interface. (Buy-and-hold is "spend `total_budget` on day 0"; DCA is "spend `budget/N` on each cadence date"; RSI/F&G is "spend remaining cash on buy signal, sell entire position on exit signal".)
- Idle cash earns 0%. This is documented in the report header.

### `metrics.py`
- Computes CAGR, total return, annualized Sharpe (rf=0), Sortino, max drawdown, win rate, number of trades, market exposure (%).
- Pure numerical; thoroughly unit-tested against hand-computed values.

### `report.py`
- Takes a `Result`, produces a single self-contained HTML file using Plotly (`include_plotlyjs="cdn"` for size, or `"inline"` for true offline durability — default **inline**).
- Sections, in order:
  1. Header — strategy name, ticker, period, params (JSON pretty-printed).
  2. Equity curve — strategy vs benchmark, log-scale toggle.
  3. Drawdown — underwater chart.
  4. Price + trade markers — candlestick or line with buy/sell arrows.
  5. Stats table — side-by-side strategy vs benchmark.
  6. Trade log — paginated HTML table.

### `manifest.py`
- `append(result: Result, html_path: str)` opens `docs/runs.json`, appends an entry, writes back atomically (write-temp-then-rename).
- Entry shape:
  ```json
  {
    "run_id": "20260516-201503-spy-ma",
    "timestamp": "2026-05-16T20:15:03Z",
    "strategy": "ma_crossover",
    "ticker": "SPY",
    "start": "2015-01-01",
    "end": "2026-05-16",
    "params": {"fast": 20, "slow": 50, "ma_type": "SMA"},
    "metrics": {"cagr": 0.094, "sharpe": 0.71, "max_drawdown": -0.23, ...},
    "bench_metrics": {"cagr": 0.108, ...},
    "html": "runs/20260516-201503-spy-ma.html"
  }
  ```

### `cli.py`
- One command: `python -m src.cli run --strategy ma_crossover --ticker SPY --start 2015-01-01 --end 2026-05-16 --params '{"fast":20,"slow":50}'`.
- Thin — exists so the agent has a stable invocation surface. Most often the agent will import `engine.run` directly.

## 5. Static Dashboard

- **No build step.** Plain HTML + vanilla JS + a tiny amount of CSS. Optional: pull in `htm` + `preact` from a CDN if the templating gets messy, but try vanilla first.
- `index.html` provides:
  - Filter bar: strategy dropdown, ticker text input, date range, free-text search.
  - Sortable table: timestamp ↓, strategy, ticker, period, CAGR, Sharpe, max DD, link.
  - Mobile: table collapses to cards.
- `app.js` fetches `runs.json` once, holds it in memory, filters/sorts client-side.
- (Stretch) Compare mode: select N rows → opens a `compare.html?ids=a,b,c` page that fetches the JSON, loads each run's equity from the manifest (or re-fetches each report's embedded data — TBD), overlays curves.

## 6. GitHub Pages Setup

- Settings → Pages → Source: `main` branch, folder `/docs`.
- No Jekyll needed; include an empty `.nojekyll` file in `/docs` to prevent Jekyll from touching files.
- Commit + push to `main` = deploy. No Actions needed for v1.

## 7. Local Development

- Python managed via `uv`. `uv sync` installs deps. `uv run pytest` runs tests.
- `.gitignore` excludes `data/`, `.venv/`, `__pycache__/`, `.DS_Store`.
- README documents the two flows: (a) "ask the agent" workflow, (b) direct CLI for debugging.

## 8. Key Design Choices & Tradeoffs

| Choice | Why | Tradeoff |
|---|---|---|
| Python + vectorbt | Mature, fast, idiomatic for this work | Engine can't run in browser — fine, we don't need it to. |
| Plotly with inline JS | Reports are durable offline, no CDN drift | Each HTML is ~3MB. Acceptable for personal use. |
| Append-only manifest | Simple, diffable, no migration story | Renames/deletes require manual edits. Fine for now. |
| No build step on /docs | Easier to inspect, faster to iterate | No TypeScript safety. App.js stays small enough to manage. |
| Single ticker only | Cuts complexity (position sizing, rebalancing) | Multi-ticker is a real v2 effort, not a v1 stretch. |
| AI agent is the UI | Zero UI to build for input | The site is read-only; you can't trigger a new run from the browser. |

## 9. Risks & Mitigations

- **yfinance breaks / rate limits.** Mitigation: aggressive local caching; data adapter interface so swapping to Stooq/Tiingo is a one-file change.
- **CNN F&G endpoint is unofficial.** It can change shape or disappear with no notice. Mitigation: isolated in `data/fear_greed.py`; cache aggressively so historical runs remain reproducible even if the endpoint dies; document an alternate-source plan (e.g. scraped GitHub archives) as a fallback if/when it breaks.
- **F&G history is short (~3 years).** Mitigation: validate the requested window in the fetcher and fail loudly; report header notes the actual data window used.
- **Manifest grows unwieldy.** At ~1KB per entry, 10k runs is 10MB — still fine for client-side load. Revisit at v2.
- **Reports become stale (yfinance revisions, splits).** Each report carries the data it was built from (inline). They are snapshots, not live views — this is a feature.
- **Look-ahead bias.** Engine must shift signals by one bar (execute next-day open) and document this clearly in the report header.
- **Survivorship bias / delisted tickers.** Out of scope; user is responsible for picking sensible tickers.

## 10. Testing Strategy

- **Unit:** `metrics.py` (golden values), each strategy's `signals()` against synthetic prices.
- **Integration:** end-to-end `engine.run` on a small fixed CSV (no network), asserting trades and final equity to the cent.
- **Smoke:** `cli.py run` produces a non-empty HTML and appends a manifest entry.
- No browser tests for the dashboard in v1; manually verify after `git push`.

## 11. Explicit Non-Goals (Reaffirmed)

- No web backend, no LLM API call from the deployed site, no auth, no DB.
- No live data, no scheduled refresh.
- No parameter optimization or walk-forward in v1.
