"""Render a backtest Result to a self-contained HTML file."""

from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go
import plotly.offline as pio
from plotly.subplots import make_subplots

from .engine import Result, StrategyRun

PLOTLY_JS_FILENAME = "plotly.min.js"  # written once into docs/ and referenced relatively


def _format_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _format_money(x: float) -> str:
    return f"${x:,.2f}"


def _stats_row(label: str, run: StrategyRun) -> str:
    m = run.metrics
    return (
        f"<tr><th>{label}</th>"
        f"<td>{_format_money(m['final_value'])}</td>"
        f"<td>{_format_money(m['cash_deployed'])}</td>"
        f"<td>{_format_pct(m['total_return'])}</td>"
        f"<td>{_format_pct(m['cagr'])}</td>"
        f"<td>{_format_pct(m['max_drawdown'])}</td>"
        f"<td>{int(m['n_buys'])}</td>"
        f"<td>{int(m['n_sells'])}</td></tr>"
    )


def render(result: Result, output_path: Path) -> Path:
    runs = [result.strategy, *result.benchmarks]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.08,
        subplot_titles=("Equity curves (same total budget)", "Cumulative cash deployed"),
    )
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    for i, run in enumerate(runs):
        color = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(x=run.equity.index, y=run.equity.values, name=run.name, line=dict(color=color)),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=run.cash_deployed.index, y=run.cash_deployed.values,
                name=f"{run.name} deployed", line=dict(color=color, dash="dot"),
                showlegend=False,
            ),
            row=2, col=1,
        )
    fig.update_yaxes(title_text="Portfolio value ($)", row=1, col=1)
    fig.update_yaxes(title_text="Cash deployed ($)", row=2, col=1)
    fig.update_layout(
        height=700, hovermode="x unified",
        legend=dict(orientation="h", y=-0.18),
        margin=dict(l=60, r=30, t=60, b=60),
    )

    # Reports live under docs/runs/, plotly.min.js under docs/. Reference is "../plotly.min.js".
    _ensure_plotly_js(output_path)
    chart_html = fig.to_html(
        full_html=False, include_plotlyjs=False, div_id="chart",
    )

    cfg = result.config
    params_json = json.dumps(cfg.params or {})
    header_html = f"""
    <header>
      <h1>{cfg.strategy} on {cfg.ticker}</h1>
      <p class="meta">
        <strong>Period:</strong> {cfg.start.isoformat()} → {cfg.end.isoformat()} &nbsp;
        <strong>Budget:</strong> {_format_money(cfg.total_budget)} &nbsp;
        <strong>Commission:</strong> {cfg.commission_bps} bps &nbsp;
        <strong>Slippage:</strong> {cfg.slippage_bps} bps
      </p>
      <p class="meta"><strong>Params:</strong> <code>{params_json}</code></p>
      <p class="note">Idle cash earns 0% in this model. Orders execute at next trading day's adjusted close.</p>
    </header>
    """

    stats_html = (
        "<section><h2>Summary</h2>"
        "<table class='stats'>"
        "<thead><tr><th></th><th>Final value</th><th>Cash deployed</th>"
        "<th>Total return</th><th>CAGR (approx)</th><th>Max drawdown</th>"
        "<th>Buys</th><th>Sells</th></tr></thead><tbody>"
        + "".join(_stats_row(run.name, run) for run in runs)
        + "</tbody></table></section>"
    )

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #222; }
    header h1 { margin-bottom: 4px; text-transform: capitalize; }
    .meta { color: #555; margin: 4px 0; }
    .note { color: #888; font-size: 0.9em; margin-top: 12px; }
    table.stats { border-collapse: collapse; width: 100%; margin-top: 12px; }
    table.stats th, table.stats td { padding: 8px 12px; border-bottom: 1px solid #eee; text-align: right; }
    table.stats th:first-child { text-align: left; }
    table.stats thead th { background: #fafafa; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
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
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full, encoding="utf-8")
    return output_path


def _ensure_plotly_js(report_path: Path) -> None:
    """Write Plotly's bundled minified JS into docs/ once so every report can share it."""
    docs_dir = report_path.parent.parent  # docs/runs/*.html -> docs/
    js_path = docs_dir / PLOTLY_JS_FILENAME
    if js_path.exists():
        return
    js_source = pio.get_plotlyjs()  # plotly.offline.get_plotlyjs()
    docs_dir.mkdir(parents=True, exist_ok=True)
    js_path.write_text(js_source, encoding="utf-8")
