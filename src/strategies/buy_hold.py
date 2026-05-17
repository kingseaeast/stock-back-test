"""Buy & hold: deposit total_budget on day one, buy as much as possible, never sell."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order


class BuyHold:
    name = "buy_hold"

    def orders(
        self,
        prices: pd.DataFrame,
        total_budget: float,
        params: dict[str, Any],
    ) -> list[Order]:
        if prices.empty:
            return []
        first_day = prices.index[0]
        return [Order(date=first_day, action=Action.DEPOSIT_AND_BUY, amount=total_budget)]
