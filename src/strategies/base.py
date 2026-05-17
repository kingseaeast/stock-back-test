"""Strategy protocol and order primitives.

A Strategy is a pure function: it takes a `context` dict (with whatever inputs
the strategy declared it needs in `data_requirements`) plus parameters, and
returns a list of Orders for the engine to execute.

Why a context dict instead of explicit args: strategies vary in what data they
need. Price-only strategies (buy-hold, DCA, RSI) take just prices. F&G needs
prices plus the F&G index. The engine loads the requested inputs once and hands
each strategy whatever it asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable

import pandas as pd


class Action(str, Enum):
    DEPOSIT_AND_BUY = "deposit_and_buy"   # add cash to portfolio, then buy with it
    BUY_ALL_CASH = "buy_all_cash"         # spend all current cash on shares
    SELL_ALL = "sell_all"                 # liquidate all shares to cash
    SELL_FRACTION = "sell_fraction"       # sell `amount` (0..1) of current shares → reserve_cash
    DEPLOY_RESERVE = "deploy_reserve"     # spend all reserve_cash on shares


@dataclass(frozen=True)
class Order:
    date: pd.Timestamp                   # the *signal* date; engine executes next bar
    action: Action
    amount: float = 0.0                  # DEPOSIT_AND_BUY: dollars; SELL_FRACTION: 0..1


@runtime_checkable
class Strategy(Protocol):
    name: ClassVar[str]
    description: ClassVar[str]                    # plain-English summary; rendered in reports
    data_requirements: ClassVar[frozenset[str]]  # e.g. frozenset({"prices"})
    param_schema: ClassVar[list[dict]]           # for HTML controls + browser JS engine
    # param_schema entry shape:
    #   {"name": "buy_below", "type": "number", "min": 0, "max": 100, "step": 1,
    #    "default": 25, "label": "Buy when below", "help": "Optional tooltip text"}
    #   {"name": "cadence", "type": "select", "options": ["monthly", "weekly"],
    #    "default": "monthly", "label": "Cadence"}
    #   {"name": "start_in_cash", "type": "boolean", "default": False,
    #    "label": "Start in cash"}

    def orders(
        self,
        context: dict[str, pd.DataFrame],
        total_budget: float,
        params: dict[str, Any],
    ) -> list[Order]:
        """Return the schedule of orders for this strategy.

        `context` keys correspond to `data_requirements`. The DataFrames are
        aligned to a shared trading-day index (prices' index).
        """
        ...
