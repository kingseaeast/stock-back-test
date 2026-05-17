# Execution Plan — Stock Strategy Backtester

Build the smallest thing that works end-to-end first, then add. Don't pre-build for strategies that aren't shipped yet.

## Milestone 1 — Walking Skeleton (DCA + buy-hold benchmark, live on GH Pages)

**Goal:** Run a DCA backtest on SPY from the CLI; produce one self-contained HTML report comparing DCA vs buy-and-hold; the GH Pages dashboard lists it and the link works.

This is intentionally minimal — no F&G, no RSI, no DCA+BTD, no filters. Just prove the loop: agent → engine → report → committed → visible on public URL.

**Tasks**
- [ ] M1.1 — `uv init`, add deps (`vectorbt`, `yfinance`, `plotly`, `pandas`, `pytest`), commit `pyproject.toml` + `.python-version` + `.gitignore` + `.nojekyll` in `/docs`.
- [ ] M1.2 — `src/data/prices.py`: `load_prices(ticker, start, end)` with Parquet cache.
- [ ] M1.3 — `src/strategies/base.py` (Strategy protocol that emits an order schedule) + `src/strategies/buy_hold.py` + `src/strategies/dca.py` (monthly cadence, default 1st trading day).
- [ ] M1.4 — `src/engine.py`: simulate from order schedule using vectorbt; produce `StrategyRun` for the requested strategy + both benchmarks. Apply commission/slippage. Forbid look-ahead.
- [ ] M1.5 — `src/metrics.py`: CAGR, total return, max drawdown, final value, total cash deployed. (Skip Sharpe/Sortino for now — not what a long-term investor optimizes on first.)
- [ ] M1.6 — `src/report.py`: single self-contained HTML with header (strategy, ticker, period, budget, params, "idle cash earns 0%" note), equity curves for strategy + both benchmarks, stats table.
- [ ] M1.7 — `src/manifest.py`: atomic append to `docs/runs.json`.
- [ ] M1.8 — `src/cli.py run --strategy dca --ticker SPY --start 2010-01-01 --end 2026-05-16 --budget 10000`.
- [ ] M1.9 — `docs/index.html` + `docs/app.js` + `docs/style.css`: load `runs.json`, render a basic table (timestamp, strategy, ticker, period, final value, link). No filters yet.
- [ ] M1.10 — Enable GH Pages (Settings → Pages → main /docs). Push. Confirm the URL renders and the report opens.
- [ ] M1.11 — `README.md`: agent workflow + manual CLI invocation.

**Exit criteria**
- `python -m src.cli run --strategy dca --ticker SPY --start 2010-01-01 --end 2026-05-16` produces an HTML report and a `runs.json` entry.
- The report shows DCA vs buy-and-hold equity curves with matching `total_budget`.
- After push, the GH Pages dashboard lists the run; clicking the link opens the report.

Once this works end-to-end, **demo it and decide** what to add next based on what actually felt clunky — don't pre-plan M2 in detail until then.

## Milestone 2 — The Other Three Strategies + Dual Benchmark Everywhere

(Add detail here only after M1 ships and you've used it.)

**Goal:** RSI, CNN F&G, and DCA+BTD all work; every report compares against both buy-and-hold and DCA-monthly; dashboard is filterable.

**Likely tasks** (treat as sketch, not commitment)
- [ ] M2.1 — `src/strategies/rsi.py` (all-in/all-out on `oversold`/`overbought`). Golden tests on synthetic prices.
- [ ] M2.2 — `src/strategies/dca_btd.py` (DCA + dip-reserve buys). Golden tests on a synthetic V-shaped drawdown.
- [ ] M2.3 — `src/data/fear_greed.py`: fetch CNN F&G JSON; cache to Parquet; fail loudly outside available window; unit-test via captured fixture (no network).
- [ ] M2.4 — `src/strategies/fear_greed.py` (all-in/all-out on F&G thresholds). Declare extra data requirement; engine joins F&G with prices.
- [ ] M2.5 — Report v2: add drawdown chart; add price + trade markers; for F&G, add an F&G subplot with threshold lines.
- [ ] M2.6 — Dashboard: strategy + ticker + date-range filters; sortable columns; mobile card layout.
- [ ] M2.7 — Seed 6–8 example runs across strategies and a couple of tickers (SPY, QQQ). Commit.

**Exit criteria**
- All four strategies usable from CLI; tests green and run offline.
- Every report shows strategy + both benchmarks side-by-side.
- Dashboard is filterable and sortable on real seeded data.

## Beyond M2 (Sketch Only)

Don't plan these in detail yet:
- Compare mode (overlay N selected runs on one chart).
- Multi-ticker portfolios.
- More strategies (Bollinger, momentum, MACD, value/dividend tilts).
- Parameter sweeps + heatmaps; walk-forward.
- A hosted chat-driven web app for non-technical users.

## Working Conventions

- **One milestone at a time.** Don't start M2 until M1 is pushed and you've used it for real.
- **Tests before strategies land.** A new strategy file ships with golden tests on synthetic series.
- **No silent failures.** Engine raises loudly on missing data, look-ahead errors, or impossible params.
- **Reports are immutable.** Never edit a committed report's HTML. Re-run; the new run gets a new `run_id`.
- **Vanilla JS dashboard until it hurts.** Re-evaluate framework choice only when a concrete pain point demands it.
