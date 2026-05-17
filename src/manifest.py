"""Append-only manifest of backtest runs (docs/runs.json)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .engine import Result

MANIFEST_PATH = Path("docs/runs.json")


def _run_to_entry(result: Result, html_relative: str) -> dict:
    cfg = result.config
    return {
        "run_id": result.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "strategy": cfg.strategy,
        "ticker": cfg.ticker.upper(),
        "start": cfg.start.isoformat(),
        "end": cfg.end.isoformat(),
        "total_budget": cfg.total_budget,
        "params": cfg.params,
        "metrics": result.strategy.metrics,
        "benchmarks": [
            {"name": b.name, "metrics": b.metrics} for b in result.benchmarks
        ],
        "html": html_relative,
    }


def append(result: Result, html_path: Path, manifest_path: Path = MANIFEST_PATH) -> dict:
    """Append a new entry for this run. Returns the entry written."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text() or "[]")
    else:
        existing = []
    if not isinstance(existing, list):
        raise ValueError(f"{manifest_path} is not a JSON list")

    # Path stored relative to /docs so the dashboard link works as a relative URL
    try:
        rel = html_path.resolve().relative_to(manifest_path.resolve().parent)
    except ValueError:
        rel = html_path
    entry = _run_to_entry(result, str(rel))
    existing.append(entry)

    # Atomic write: temp file in same dir, then rename
    with tempfile.NamedTemporaryFile(
        "w", dir=manifest_path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        json.dump(existing, tmp, indent=2, default=str)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, manifest_path)
    return entry
