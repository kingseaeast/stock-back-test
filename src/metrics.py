"""Backtest metrics.

Kept intentionally minimal for v1: CAGR, total return, max drawdown, final value,
cash deployed. Sharpe/Sortino come later.

`equity` is the portfolio value over time (cash + share value).
`cash_deployed` is cumulative dollars actually put into the portfolio
  (deposits, not purchases). For buy-hold this is a step at t=0; for DCA it
  ramps up over time. Used to compute money-weighted-ish return helpers.
"""

from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def total_return(equity: pd.Series, cash_deployed: pd.Series) -> float:
    """Final value divided by total cash deployed, minus 1.

    For DCA this is *not* time-weighted; it's a simple multiple-on-money.
    For buy-hold it equals (final / initial) - 1.
    """
    deployed = float(cash_deployed.iloc[-1])
    if deployed <= 0:
        return 0.0
    return float(equity.iloc[-1]) / deployed - 1.0


def cagr(equity: pd.Series, cash_deployed: pd.Series) -> float:
    """Annualized return based on total deployed capital and the full window.

    Approximation for DCA (treats all cash as if deployed at t=0). Documented
    in the report; revisit with money-weighted return in v2 if it matters.
    """
    deployed = float(cash_deployed.iloc[-1])
    if deployed <= 0 or len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    final = float(equity.iloc[-1])
    if final <= 0:
        return -1.0
    return (final / deployed) ** (1 / years) - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough decline in equity, as a negative fraction."""
    if equity.empty:
        return 0.0
    running_peak = equity.cummax()
    drawdown = (equity - running_peak) / running_peak.replace(0, math.nan)
    dd_min = drawdown.min()
    return float(dd_min) if not math.isnan(dd_min) else 0.0


def summarize(
    equity: pd.Series,
    cash_deployed: pd.Series,
    n_buys: int,
    n_sells: int,
) -> dict[str, float]:
    return {
        "final_value": float(equity.iloc[-1]),
        "cash_deployed": float(cash_deployed.iloc[-1]),
        "total_return": total_return(equity, cash_deployed),
        "cagr": cagr(equity, cash_deployed),
        "max_drawdown": max_drawdown(equity),
        "n_buys": float(n_buys),
        "n_sells": float(n_sells),
    }
