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
    DEPOSIT_AND_BUY = "deposit_and_buy"  # add cash to portfolio, then buy with it
    BUY_ALL_CASH = "buy_all_cash"        # spend all current cash on shares
    SELL_ALL = "sell_all"                # liquidate all shares to cash


@dataclass(frozen=True)
class Order:
    date: pd.Timestamp                   # the *signal* date; engine executes next bar
    action: Action
    amount: float = 0.0                  # only used by DEPOSIT_AND_BUY


@runtime_checkable
class Strategy(Protocol):
    name: ClassVar[str]
    data_requirements: ClassVar[frozenset[str]]  # e.g. frozenset({"prices"})

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
