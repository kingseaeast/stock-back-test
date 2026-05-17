"""Render a backtest Result to a self-contained HTML file."""

from __future__ import annotations

import json
from pathlib import Path

import html as html_lib

import pandas as pd
import plotly.graph_objects as go
import plotly.offline as pio
from plotly.subplots import make_subplots

from . import strategies
from .engine import Result, StrategyRun, Trade

PLOTLY_JS_FILENAME = "plotly.min.js"  # written once into docs/ and referenced relatively
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]


def _format_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _format_money(x: float) -> str:
    return f"${x:,.2f}"


def _stats_row(label: str, run: StrategyRun, *, is_strategy: bool) -> str:
    m = run.metrics
    cls = " class='strategy-row'" if is_strategy else ""
    return (
        f"<tr{cls}><th>{label}</th>"
        f"<td>{_format_money(m['final_value'])}</td>"
        f"<td>{_format_money(m['cash_deployed'])}</td>"
        f"<td>{_format_pct(m['total_return'])}</td>"
        f"<td>{_format_pct(m['cagr'])}</td>"
        f"<td>{_format_pct(m['max_drawdown'])}</td>"
        f"<td>{int(m['n_buys'])}</td>"
        f"<td>{int(m['n_sells'])}</td></tr>"
    )


def _trade_log_html(trades: list[Trade], strategy_name: str) -> str:
    """Render the strategy's trade log as a scrollable table."""
    if not trades:
        return (
            "<section><h2>Trade log</h2>"
            "<p class='muted'>No trades executed.</p></section>"
        )

    rows = []
    running_shares = 0.0
    running_cash_in = 0.0
    for i, t in enumerate(trades, start=1):
        if t.side == "buy":
            running_shares += t.shares
            running_cash_in += t.notional + t.commission
            side_class = "buy"
        else:
            running_shares -= t.shares
            running_cash_in -= t.notional - t.commission
            side_class = "sell"
        rows.append(
            f"<tr>"
            f"<td class='num'>{i}</td>"
            f"<td>{t.date.strftime('%Y-%m-%d')}</td>"
            f"<td class='side {side_class}'>{t.side}</td>"
            f"<td class='num'>{t.shares:,.4f}</td>"
            f"<td class='num'>{_format_money(t.price)}</td>"
            f"<td class='num'>{_format_money(t.notional)}</td>"
            f"<td class='num'>{_format_money(t.commission)}</td>"
            f"<td class='num'>{running_shares:,.4f}</td>"
            f"</tr>"
        )

    n_buys = sum(1 for t in trades if t.side == "buy")
    n_sells = sum(1 for t in trades if t.side == "sell")
    return (
        f"<section><h2>Trade log <span class='muted'>"
        f"({len(trades)} trades — {n_buys} buys, {n_sells} sells)</span></h2>"
        "<div class='trade-log-wrap'><table class='trade-log'>"
        "<thead><tr>"
        "<th class='num'>#</th><th>Date</th><th>Side</th>"
        "<th class='num'>Shares</th><th class='num'>Exec price</th>"
        "<th class='num'>Notional</th><th class='num'>Commission</th>"
        "<th class='num'>Shares held</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def _drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    # Where peak is 0 (pre-deployment days), drawdown is undefined -> fill with 0.
    safe_peak = peak.where(peak > 0)
    return ((equity - peak) / safe_peak).fillna(0.0).astype(float)


def render(result: Result, output_path: Path) -> Path:
    runs = [result.strategy, *result.benchmarks]
    cfg = result.config

    # Pull price + (optionally) F&G data the strategy used. Re-load from cache to
    # avoid threading them through `Result` — cheap and avoids API churn.
    from .data.prices import load_prices
    prices = load_prices(cfg.ticker, cfg.start, cfg.end)
    show_fg = cfg.strategy == "fear_greed"
    fg_series: pd.Series | None = None
    fg_index_col = "fear_greed"
    if show_fg:
        from .data.fear_greed import load_fear_greed
        fg_index_col = cfg.params.get("index_type", "fear_greed")
        fg_source = cfg.data_options.get("fg_source", "cnn")
        fg_df = load_fear_greed(cfg.start, cfg.end, source=fg_source)
        fg_series = fg_df[fg_index_col].reindex(prices.index.union(fg_df.index)).ffill().reindex(prices.index)

    # Subplot layout
    rows = 5 if show_fg else 4
    row_heights = [0.30, 0.15, 0.20, 0.10, 0.25] if show_fg else [0.32, 0.18, 0.25, 0.25]
    titles = [
        "Equity curves (same total budget)",
        "Drawdown",
        f"{cfg.ticker} price + strategy trades",
        "Cumulative cash deployed",
    ]
    if show_fg:
        titles.append(f"CNN {fg_index_col.replace('_', ' ').title()}")
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        row_heights=row_heights, vertical_spacing=0.06,
        subplot_titles=titles,
    )

    # Row 1: equity curves
    for i, run in enumerate(runs):
        fig.add_trace(
            go.Scatter(
                x=run.equity.index, y=run.equity.values, name=run.name,
                line=dict(color=PALETTE[i % len(PALETTE)]),
            ),
            row=1, col=1,
        )
    fig.update_yaxes(title_text="Value ($)", row=1, col=1)

    # Row 2: drawdown
    for i, run in enumerate(runs):
        dd = _drawdown(run.equity)
        fig.add_trace(
            go.Scatter(
                x=dd.index, y=(dd * 100).values, name=f"{run.name} dd",
                line=dict(color=PALETTE[i % len(PALETTE)]), showlegend=False,
            ),
            row=2, col=1,
        )
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)

    # Row 3: price with strategy's trade markers
    fig.add_trace(
        go.Scatter(
            x=prices.index, y=prices["adj_close"].astype(float),
            name=f"{cfg.ticker} adj close", line=dict(color="#555"), showlegend=False,
        ),
        row=3, col=1,
    )
    buy_trades = [t for t in result.strategy.trades if t.side == "buy"]
    sell_trades = [t for t in result.strategy.trades if t.side == "sell"]
    if buy_trades:
        fig.add_trace(
            go.Scatter(
                x=[t.date for t in buy_trades],
                y=[float(prices["adj_close"].loc[t.date]) for t in buy_trades],
                mode="markers", name="buy",
                marker=dict(symbol="triangle-up", size=10, color="#2ca02c"),
            ),
            row=3, col=1,
        )
    if sell_trades:
        fig.add_trace(
            go.Scatter(
                x=[t.date for t in sell_trades],
                y=[float(prices["adj_close"].loc[t.date]) for t in sell_trades],
                mode="markers", name="sell",
                marker=dict(symbol="triangle-down", size=10, color="#d62728"),
            ),
            row=3, col=1,
        )
    fig.update_yaxes(title_text="Price ($)", row=3, col=1)

    # Row 4: cumulative cash deployed
    for i, run in enumerate(runs):
        fig.add_trace(
            go.Scatter(
                x=run.cash_deployed.index, y=run.cash_deployed.values,
                name=f"{run.name} deployed", line=dict(color=PALETTE[i % len(PALETTE)], dash="dot"),
                showlegend=False,
            ),
            row=4, col=1,
        )
    fig.update_yaxes(title_text="Deployed ($)", row=4, col=1)

    # Row 5: F&G index with threshold lines
    if show_fg and fg_series is not None:
        buy_below = float(cfg.params.get("buy_below", 25))
        exit_above = float(cfg.params.get("exit_above", 75))
        fig.add_trace(
            go.Scatter(
                x=fg_series.index, y=fg_series.values, name=fg_index_col,
                line=dict(color="#8e44ad"), showlegend=False,
            ),
            row=5, col=1,
        )
        fig.add_hline(y=buy_below, line=dict(color="#2ca02c", dash="dash"), row=5, col=1,
                      annotation_text=f"buy < {buy_below}", annotation_position="top left")
        fig.add_hline(y=exit_above, line=dict(color="#d62728", dash="dash"), row=5, col=1,
                      annotation_text=f"exit > {exit_above}", annotation_position="bottom left")
        fig.update_yaxes(title_text="F&G score", range=[0, 100], row=5, col=1)

    fig.update_layout(
        height=240 * rows, hovermode="x unified",
        legend=dict(orientation="h", y=-0.10),
        margin=dict(l=60, r=30, t=60, b=60),
    )

    _ensure_plotly_js(output_path)
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False, div_id="chart")

    params_json = json.dumps(cfg.params or {})
    strategy_cls = strategies.get(cfg.strategy)
    description = html_lib.escape(getattr(strategy_cls, "description", "") or "")
    data_options_html = ""
    if cfg.data_options:
        data_options_html = (
            f'<p class="meta"><strong>Data options:</strong> '
            f'<code>{html_lib.escape(json.dumps(cfg.data_options))}</code></p>'
        )
    header_html = f"""
    <header>
      <h1>{cfg.strategy} on {cfg.ticker}</h1>
      <p class="description">{description}</p>
      <p class="meta">
        <strong>Period:</strong> {cfg.start.isoformat()} → {cfg.end.isoformat()} &nbsp;
        <strong>Budget:</strong> {_format_money(cfg.total_budget)} &nbsp;
        <strong>Commission:</strong> {cfg.commission_bps} bps &nbsp;
        <strong>Slippage:</strong> {cfg.slippage_bps} bps
      </p>
      <p class="meta"><strong>Params:</strong> <code>{params_json}</code></p>
      {data_options_html}
      <p class="note">Idle cash earns 0% in this model. Orders execute at next trading day's adjusted close.</p>
    </header>
    """

    stats_rows = [_stats_row(result.strategy.name, result.strategy, is_strategy=True)]
    stats_rows += [_stats_row(b.name, b, is_strategy=False) for b in result.benchmarks]
    stats_html = (
        "<section><h2>Summary</h2>"
        "<table class='stats'>"
        "<thead><tr><th></th><th>Final value</th><th>Cash deployed</th>"
        "<th>Total return</th><th>CAGR (approx)</th><th>Max drawdown</th>"
        "<th>Buys</th><th>Sells</th></tr></thead><tbody>"
        + "".join(stats_rows)
        + "</tbody></table></section>"
    )

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #222; }
    header h1 { margin-bottom: 4px; text-transform: capitalize; }
    .meta { color: #555; margin: 4px 0; }
    .description { color: #444; font-size: 0.95em; margin: 6px 0 12px; line-height: 1.55; max-width: 850px; }
    .note { color: #888; font-size: 0.9em; margin-top: 12px; }
    .muted { color: #888; font-weight: 400; font-size: 0.85em; }
    section { margin-top: 28px; }
    section h2 { margin-bottom: 8px; }
    table.stats { border-collapse: collapse; width: 100%; margin-top: 12px; }
    table.stats th, table.stats td { padding: 8px 12px; border-bottom: 1px solid #eee; text-align: right; }
    table.stats th:first-child { text-align: left; }
    table.stats thead th { background: #fafafa; }
    table.stats tr.strategy-row { background: #fffaf0; font-weight: 600; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
    .trade-log-wrap { max-height: 480px; overflow-y: auto; border: 1px solid #eee; border-radius: 4px; }
    table.trade-log { border-collapse: collapse; width: 100%; font-size: 13px; }
    table.trade-log th, table.trade-log td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; text-align: left; white-space: nowrap; }
    table.trade-log thead th { background: #fafafa; position: sticky; top: 0; z-index: 1; }
    table.trade-log .num { text-align: right; font-variant-numeric: tabular-nums; }
    table.trade-log .side { font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }
    table.trade-log .side.buy { color: #2ca02c; }
    table.trade-log .side.sell { color: #d62728; }
    table.trade-log tbody tr:hover { background: #fafafa; }
    """

    full = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cfg.strategy} · {cfg.ticker} · {result.run_id}</title>
  <script src="../{PLOTLY_JS_FILENAME}"></script>
  <style>{css}</style>
</head>
<body>
  {header_html}
  {stats_html}
  <section><h2>Charts</h2>{chart_html}</section>
  {_trade_log_html(result.strategy.trades, result.strategy.name)}
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full, encoding="utf-8")
    return output_path


def _ensure_plotly_js(report_path: Path) -> None:
    """Write Plotly's bundled minified JS into docs/ once so every report can share it."""
    docs_dir = report_path.parent.parent
    js_path = docs_dir / PLOTLY_JS_FILENAME
    if js_path.exists():
        return
    js_source = pio.get_plotlyjs()
    docs_dir.mkdir(parents=True, exist_ok=True)
    js_path.write_text(js_source, encoding="utf-8")
