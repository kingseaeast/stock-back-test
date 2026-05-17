"""Strategy protocol and order primitives.

A Strategy is a pure function: it takes a price DataFrame plus parameters,
and returns a list of Orders to be executed by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

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
    name: str

    def orders(
        self,
        prices: pd.DataFrame,
        total_budget: float,
        params: dict[str, Any],
    ) -> list[Order]:
        """Return the schedule of orders for this strategy on this price series."""
        ...
