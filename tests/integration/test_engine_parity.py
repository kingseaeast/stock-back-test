"""Integration test: Python and JS engines must agree on every committed report.

Parameterized per report so failures surface as e.g.
    FAILED tests/integration/test_engine_parity.py::test_report_parity[buy_hold_SPY]

Marked `integration` and skipped by default. Run via:
    uv run pytest -m integration

Prereqs:
  - Node on PATH (loads docs/engine.js)
  - Local Parquet caches under data/ (Python engine re-loads from these)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.check_engine_parity import (
    REPORTS_DIR,
    TOLERANCE,
    compare,
    extract_state,
    js_metrics,
    python_metrics,
)

pytestmark = pytest.mark.integration


def _report_ids() -> list[Path]:
    if not REPORTS_DIR.is_dir():
        return []
    return sorted(REPORTS_DIR.glob("*.html"))


def _report_id(path: Path) -> str:
    # e.g. "20260517-053043212_buy_hold_SPY.html" -> "buy_hold_SPY"
    stem = path.stem.split("_", 1)
    return stem[1] if len(stem) == 2 else path.stem


@pytest.fixture(scope="module", autouse=True)
def _require_node():
    if shutil.which("node") is None:
        pytest.skip("`node` not on PATH; install Node.js to run the parity check.")


@pytest.fixture(scope="module", autouse=True)
def _require_reports():
    if not _report_ids():
        pytest.skip(f"No reports found in {REPORTS_DIR}")


@pytest.mark.parametrize("report", _report_ids() or [None], ids=lambda p: _report_id(p) if p else "no-reports")
def test_report_parity(report: Path):
    """Every committed report must produce identical metrics in both engines
    (within TOLERANCE defined in scripts/check_engine_parity.py)."""
    if report is None:
        pytest.skip("No reports to check")
    state = extract_state(report)
    py = python_metrics(state)
    js = js_metrics(state)
    diffs = compare(py, js, source=str(report))
    failing = [d for d in diffs if d.fails]
    if failing:
        msg_lines = [f"  {d.metric}: py={d.py:.6f}  js={d.js:.6f}  Δ={d.delta:+.6f}  tol={d.tolerance}"
                     for d in failing]
        pytest.fail(
            f"{len(failing)} metric(s) diverged on {report.name}:\n"
            + "\n".join(msg_lines)
        )
