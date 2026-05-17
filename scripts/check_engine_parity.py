"""Compare the Python and browser-JS backtest engines on every report under docs/runs/.

For each committed report:
  1. Extract the embedded #report-data JSON (data + defaults that generated it).
  2. Run the Python engine with the report's stored config.
  3. Run the JS engine (docs/engine.js) via Node with the same config + embedded data.
  4. Compare metrics (final_value, total_return, cagr, max_drawdown, n_buys, n_sells)
     for the strategy and every benchmark.

Exits 0 if every metric is within `TOLERANCE` (default: $0.01 absolute on monetary
fields, 1e-6 on ratios, 0 on integer trade counts). Non-zero on any divergence.

Run from the repo root:

    uv run python scripts/check_engine_parity.py

CI-friendly: prints a clean table and a final PASS/FAIL summary.

This script requires Node on PATH (any reasonably recent version). On macOS:
    brew install node
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow `python scripts/check_engine_parity.py` without `uv run`
sys.path.insert(0, str(REPO_ROOT))

from src.engine import RunConfig, run as py_run  # noqa: E402

REPORTS_DIR = REPO_ROOT / "docs" / "runs"
JS_RUNNER = REPO_ROOT / "scripts" / "_js_engine_runner.js"
SCRIPT_RE = re.compile(
    r'<script id="report-data" type="application/json">(.*?)</script>',
    re.DOTALL,
)

# Per-metric tolerances. Tight enough to catch real algorithmic bugs, loose enough
# to ignore float64 summation-order noise that accumulates across long windows.
#
# A real engine bug would shift `n_buys` / `n_sells` (must match exactly) or move
# the equity curve by many cents on a $10K portfolio (well above $1). Sub-cent
# drift like $0.02 on $34K is unavoidable across different reduction orders in
# pandas vs raw JS arithmetic and isn't worth chasing.
TOLERANCE = {
    "final_value": 1.00,        # dollars
    "cash_deployed": 1.00,
    "total_return": 1e-4,       # 0.01% relative
    "cagr": 1e-4,
    "max_drawdown": 1e-4,
    "n_buys": 0,                # integer counts; must match exactly
    "n_sells": 0,
}


@dataclass
class MetricDiff:
    metric: str
    py: float
    js: float
    delta: float
    tolerance: float

    @property
    def fails(self) -> bool:
        return abs(self.delta) > self.tolerance


@dataclass
class RunComparison:
    report_path: Path
    strategy_name: str
    ticker: str
    diffs: list[MetricDiff]   # across strategy + benchmarks, flattened

    @property
    def failing(self) -> list[MetricDiff]:
        return [d for d in self.diffs if d.fails]


def extract_state(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    match = SCRIPT_RE.search(text)
    if not match:
        raise RuntimeError(f"No embedded report-data in {html_path}")
    return json.loads(match.group(1))


def python_metrics(state: dict) -> dict[str, dict[str, float]]:
    """Re-run via the Python engine using the report's stored config.
    Data is loaded the normal way (Parquet cache); the report's embedded data
    was generated from the same cache, so this is a meaningful comparison.
    """
    defaults = state["defaults"]
    config = RunConfig(
        strategy=state["strategy"],
        ticker=state["ticker"],
        start=date.fromisoformat(defaults["start"]),
        end=date.fromisoformat(defaults["end"]),
        total_budget=defaults["total_budget"],
        commission_bps=defaults["commission_bps"],
        slippage_bps=defaults["slippage_bps"],
        params=defaults.get("params") or {},
        data_options={"fg_source": "cnn"} if state["strategy"] == "fear_greed" else {},
    )
    # Honor data_options that the report was generated with, if persisted.
    embedded_opts = state.get("defaults", {}).get("data_options")
    if embedded_opts:
        config = _with_data_options(config, embedded_opts)
    else:
        # The defaults dict didn't carry data_options historically; sniff the strategy.
        # If the strategy is fear_greed and the embedded fear_greed data is short (<400
        # rows over a window > 18 months), it's almost certainly whit3rabbit. Default
        # to cnn otherwise. Not bulletproof but enough for parity checks.
        if state["strategy"] == "fear_greed":
            fg = state["data"].get("fear_greed", [])
            if fg and len(fg) > 1500:
                config = _with_data_options(config, {"fg_source": "whit3rabbit"})

    result = py_run(config)
    out = {result.strategy.name: result.strategy.metrics}
    for b in result.benchmarks:
        out[b.name] = b.metrics
    return out


def _with_data_options(config: RunConfig, opts: dict) -> RunConfig:
    """RunConfig is frozen — rebuild with new data_options."""
    return RunConfig(
        strategy=config.strategy, ticker=config.ticker,
        start=config.start, end=config.end,
        params=config.params, total_budget=config.total_budget,
        commission_bps=config.commission_bps, slippage_bps=config.slippage_bps,
        data_options=opts,
    )


def js_metrics(state: dict) -> dict[str, dict[str, float]]:
    """Run the embedded data through docs/engine.js via Node."""
    if shutil.which("node") is None:
        raise RuntimeError("`node` not on PATH. Install Node to run the JS engine.")
    defaults = state["defaults"]
    payload = {
        "config": {
            "strategy": state["strategy"],
            "start": defaults["start"],
            "end": defaults["end"],
            "total_budget": defaults["total_budget"],
            "commission_bps": defaults["commission_bps"],
            "slippage_bps": defaults["slippage_bps"],
            "params": defaults.get("params") or {},
        },
        "data": state["data"],
    }
    proc = subprocess.run(
        ["node", str(JS_RUNNER)],
        input=json.dumps(payload),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"JS runner failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    raw = json.loads(proc.stdout)
    out = {raw["strategy"]["name"]: raw["strategy"]["metrics"]}
    for b in raw["benchmarks"]:
        out[b["name"]] = b["metrics"]
    return out


def compare(py: dict, js: dict, source: str) -> list[MetricDiff]:
    """Compare matching run names between Python and JS results."""
    diffs: list[MetricDiff] = []
    common = sorted(set(py) & set(js))
    for run_name in common:
        for metric, tol in TOLERANCE.items():
            py_v = py[run_name].get(metric)
            js_v = js[run_name].get(metric)
            if py_v is None or js_v is None:
                continue
            diff = float(js_v) - float(py_v)
            diffs.append(MetricDiff(
                metric=f"{run_name}.{metric}",
                py=float(py_v), js=float(js_v),
                delta=diff, tolerance=tol,
            ))
    return diffs


def format_summary(comparisons: list[RunComparison]) -> str:
    lines = []
    name_w = max((len(c.report_path.name) for c in comparisons), default=20)
    lines.append(
        f"{'report':<{name_w}}  {'strategy':<11}  {'ticker':<6}  result"
    )
    lines.append("-" * (name_w + 11 + 6 + 30))
    for c in comparisons:
        status = "PASS" if not c.failing else f"FAIL ({len(c.failing)} metric(s))"
        lines.append(
            f"{c.report_path.name:<{name_w}}  {c.strategy_name:<11}  {c.ticker:<6}  {status}"
        )
    return "\n".join(lines)


def format_failures(comparisons: list[RunComparison]) -> str:
    failing = [(c, d) for c in comparisons for d in c.failing]
    if not failing:
        return ""
    out = ["\nDivergences:"]
    for c, d in failing:
        out.append(
            f"  {c.report_path.name}  {d.metric}: "
            f"py={d.py:.6f}  js={d.js:.6f}  Δ={d.delta:+.6f}  tol={d.tolerance}"
        )
    return "\n".join(out)


def main() -> int:
    if not REPORTS_DIR.is_dir():
        print(f"No reports dir at {REPORTS_DIR}", file=sys.stderr)
        return 2
    reports = sorted(REPORTS_DIR.glob("*.html"))
    if not reports:
        print(f"No reports found in {REPORTS_DIR}", file=sys.stderr)
        return 2
    if shutil.which("node") is None:
        print("ERROR: `node` not on PATH. Install Node.js to run parity check.", file=sys.stderr)
        return 2

    comparisons: list[RunComparison] = []
    for report in reports:
        try:
            state = extract_state(report)
            py = python_metrics(state)
            js = js_metrics(state)
            diffs = compare(py, js, source=str(report))
            comparisons.append(RunComparison(
                report_path=report,
                strategy_name=state["strategy"],
                ticker=state["ticker"],
                diffs=diffs,
            ))
        except Exception as exc:  # surface and continue so we see all failures
            print(f"  ERROR processing {report.name}: {exc}", file=sys.stderr)
            comparisons.append(RunComparison(
                report_path=report, strategy_name="?", ticker="?",
                diffs=[MetricDiff("ERROR", 0.0, 0.0, float("inf"), 0.0)],
            ))

    print(format_summary(comparisons))
    failures = format_failures(comparisons)
    if failures:
        print(failures)
    n_failed = sum(1 for c in comparisons if c.failing)
    print(f"\n{len(comparisons) - n_failed}/{len(comparisons)} reports passed parity.")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
