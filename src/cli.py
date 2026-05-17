"""CLI entrypoint: `python -m src.cli run ...`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import strategies
from .engine import RunConfig, run
from .manifest import append as append_manifest
from .report import render

REPORTS_DIR = Path("docs/runs")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_params(s: str) -> dict:
    if not s:
        return {}
    try:
        out = json.loads(s)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--params must be valid JSON: {e}")
    if not isinstance(out, dict):
        raise SystemExit("--params must be a JSON object")
    return out


def cmd_run(args: argparse.Namespace) -> int:
    data_options: dict = {}
    if args.fg_source:
        data_options["fg_source"] = args.fg_source
    config = RunConfig(
        strategy=args.strategy,
        ticker=args.ticker.upper(),
        start=args.start,
        end=args.end,
        params=args.params,
        total_budget=args.budget,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        data_options=data_options,
    )
    result = run(config)
    html_path = REPORTS_DIR / f"{result.run_id}.html"
    render(result, html_path)
    entry = append_manifest(result, html_path)

    print(f"Run written: {html_path}")
    print(f"Manifest entry: {entry['run_id']}")
    m = result.strategy.metrics
    print(
        f"  strategy {config.strategy:<10s} final=${m['final_value']:,.2f} "
        f"deployed=${m['cash_deployed']:,.2f} "
        f"total_return={m['total_return'] * 100:.2f}% "
        f"max_dd={m['max_drawdown'] * 100:.2f}%"
    )
    for b in result.benchmarks:
        bm = b.metrics
        print(
            f"  bench    {b.name:<10s} final=${bm['final_value']:,.2f} "
            f"deployed=${bm['cash_deployed']:,.2f} "
            f"total_return={bm['total_return'] * 100:.2f}% "
            f"max_dd={bm['max_drawdown'] * 100:.2f}%"
        )
    return 0


def cmd_list_strategies(_: argparse.Namespace) -> int:
    for name in sorted(strategies.REGISTRY):
        cls = strategies.REGISTRY[name]
        print(f"{name}\t{getattr(cls, 'description', '')}")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    cls = strategies.get(args.strategy)
    print(f"# {cls.name}\n")
    print(getattr(cls, "description", "(no description)"))
    print()
    print(f"Data requirements: {sorted(cls.data_requirements)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stock-back-test")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="Run a backtest and write an HTML report")
    pr.add_argument("--strategy", required=True, choices=sorted(strategies.REGISTRY))
    pr.add_argument("--ticker", required=True)
    pr.add_argument("--start", required=True, type=_parse_date)
    pr.add_argument("--end", required=True, type=_parse_date)
    pr.add_argument("--budget", type=float, default=10_000.0)
    pr.add_argument("--params", type=_parse_params, default={})
    pr.add_argument("--commission-bps", type=float, default=5.0)
    pr.add_argument("--slippage-bps", type=float, default=5.0)
    pr.add_argument(
        "--fg-source", choices=["cnn", "whit3rabbit"], default=None,
        help="F&G data source (default cnn ~5.5y; whit3rabbit ~15y back to 2011)",
    )
    pr.set_defaults(func=cmd_run)

    pl = sub.add_parser("list-strategies", help="List registered strategies (name + one-line description)")
    pl.set_defaults(func=cmd_list_strategies)

    pd = sub.add_parser("describe", help="Print a strategy's full description and data requirements")
    pd.add_argument("strategy", choices=sorted(strategies.REGISTRY))
    pd.set_defaults(func=cmd_describe)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
