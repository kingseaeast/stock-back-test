# Product Requirements — Stock Strategy Backtester

## 1. Summary

A personal tool for backtesting simple stock trading strategies on daily price data. The backtest **engine runs locally**, driven by an AI coding agent (e.g. Claude Code) in conversation. Each run produces a self-contained HTML report. A minimal static dashboard on **GitHub Pages** indexes all runs so results can be browsed, filtered, and shared via URL.

The product is the *workflow*: natural-language conversation → local backtest → committed HTML report → public dashboard.

## 2. Goals

- Let me (the user) describe a strategy in natural language and get a credible backtest in under a minute of agent work.
- Keep all execution local — no hosted services, no API keys in the repo, no costs.
- Produce reports that are durable, shareable, and viewable without running anything (just open a URL).
- Make it trivial to compare runs over time as I iterate on strategies.

## 3. Non-Goals (v1)

- Live trading, paper trading, broker integration.
- Intraday data, options, futures, crypto.
- Portfolio optimization, risk parity, multi-asset allocation.
- A hosted web app, user accounts, or multi-tenant anything.
- An in-browser chat UI — the AI agent lives in the user's terminal.
- Real-time data; reports reflect the moment they were generated.

## 4. Users

Single user: me — a long-term investor, not a trader. The tool exists to evaluate simple, low-touch, multi-year strategies. The design assumes one person, one repo, one machine. No auth, no concurrency, no rate limits.

## 5. User Workflow

1. In a terminal, I open an AI coding agent in the repo.
2. I describe a strategy in plain English ("buy SPY when the 20-day SMA crosses above the 50-day, sell on the reverse cross, from 2015 to today").
3. The agent picks a built-in strategy template, fills parameters, fetches data, runs the backtest, and writes an HTML report into `/docs/runs/<timestamp>-<slug>.html` plus an entry in `/docs/runs.json`.
4. I commit and push. GitHub Pages publishes the updated site automatically.
5. I (or anyone I share the URL with) browse the dashboard, filter runs by strategy/ticker/date, and open any individual report.

## 6. Functional Requirements

### 6.1 Backtest Engine (local)
- Fetch daily OHLCV via `yfinance`; cache to local Parquet to avoid refetching.
- Support a fixed library of strategies (see 6.2). Each strategy is parameterized.
- Single-ticker backtests only in v1.
- Configurable per run: ticker, date range, `total_budget` (default $10,000), commission (bps), slippage (bps).
- Every strategy deploys the **same `total_budget`** so final values are directly comparable. Cash sitting idle earns 0% in v1 (no money-market modeling — note this in the report so it's not invisible).
- Produce: equity curve, drawdown series, trade log, summary metrics (CAGR, total return, Sharpe, Sortino, max drawdown, # buys/sells, exposure %, total cash deployed, final value).
- Always run **two benchmarks** alongside the chosen strategy: **buy-and-hold** and **DCA-monthly**. Both use the same `total_budget` and same window.

### 6.2 Strategies (v1)
- **Buy & hold** — deploy entire `total_budget` at t=0. Always present as a benchmark on every report.
- **DCA (dollar-cost averaging)** — deploy `total_budget / N` on a fixed cadence. Params: `cadence` (default `monthly`; also `weekly`, `biweekly`), `day_of_period` (default 1st trading day of period). Always present as a benchmark on every report.
- **DCA + BTD (buy the dip)** — DCA contributes ~`(1 − dip_reserve_pct)` of `total_budget` on cadence; the remaining reserve buys when price closes ≥ `dip_threshold_pct` below its trailing `dip_lookback` high. Params: `cadence`, `dip_reserve_pct` (default 0.20), `dip_threshold_pct` (default 0.10), `dip_lookback` (default 90 trading days). Reserve buys are sized as `reserve_remaining / max_remaining_dip_buys` (configurable; default fully deploy on first qualifying dip).
- **RSI buy/sell** — long-term oversold/overbought. Starts 100% cash; goes 100% invested when RSI(period) < `oversold`, exits to 100% cash when RSI > `overbought`. Params: `period` (default 14), `oversold` (default 30), `overbought` (default 70).
- **CNN Fear & Greed buy/sell** — same shape as RSI but driven by CNN's daily F&G index. Params: `buy_below` (default 25), `exit_above` (default 75), `index_type` (default `fear_greed`). Note: CNN's public history is ~3 years, so backtest windows for this strategy are shorter than for price-only strategies.

All v1 strategies are "set and forget" — appropriate for a long-term investor running quarterly check-ins, not a day trader. Additional strategies are an explicit v2 concern; the engine must make adding one straightforward.

### 6.3 Report (per run)
- Single self-contained HTML file. All charts inline via Plotly (no external JS at runtime).
- Sections: header (strategy, ticker, period, params), equity curve vs buy-and-hold, drawdown chart, trade markers on price chart, stats table, trade log table, parameters block.
- Filename pattern: `runs/YYYY-MM-DD-HHMMSS_<strategy>_<ticker>.html`.

### 6.4 Run Manifest
- A single `docs/runs.json` file lists every run with metadata (timestamp, strategy, ticker, period, key metrics, HTML path).
- Engine appends a new entry on each run; never rewrites old ones.

### 6.5 Static Dashboard (GitHub Pages)
- Lives in `/docs`. GH Pages serves `/docs` from `main`.
- Single-page static site (HTML + vanilla JS or a tiny framework — no build step preferred).
- Loads `runs.json`, renders a sortable/filterable table: timestamp, strategy, ticker, period, CAGR, Sharpe, max drawdown, link to report.
- Filters: strategy name, ticker, date range.
- Click row → opens the run's HTML report.
- (Stretch) compare-mode: select 2–4 runs, render overlaid equity curves on one chart.

## 7. Success Criteria

- I can go from "I want to test strategy X" to a committed report in a single agent conversation, under ~2 minutes wall time.
- Reports remain viewable a year later with no rebuild (self-contained HTML).
- Adding a new built-in strategy takes <30 min for the agent.
- The dashboard is usable on mobile without horizontal scroll.

## 8. Out of Scope / Future

- **v2:** multi-ticker portfolios; more strategies (momentum/breakout, Bollinger, MACD); parameter sweeps and a heatmap view; walk-forward validation.
- **v3:** a hosted chat-driven web app where non-technical users can run backtests without a terminal. (This brings back the backend/LLM/secrets questions that we deferred.)

## 9. Constraints & Decisions

- **Hosting:** GitHub Pages only. No backend, no serverless functions.
- **Engine language:** Python (vectorbt + yfinance + Plotly). The AI agent generates and runs Python locally.
- **Driver:** any AI coding agent run by the user; no LLM is called by the deployed site.
- **Data:** yfinance for price data; CNN F&G unofficial JSON endpoint for the F&G index. Adapter layer keeps sources pluggable.
- **Repo layout:** single repo; `/src` (engine), `/docs` (published site + reports + manifest), `/data` (cached price data, gitignored).
