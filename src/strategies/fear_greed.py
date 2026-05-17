"""Fear & Greed contrarian: buy when fearful, sell when greedy.

Long-only. Mirrors the RSI strategy's all-in/all-out shape but uses the CNN F&G
index instead of a price-derived indicator.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order


class FearGreed:
    name = "fear_greed"
    description = (
        "Contrarian timing using CNN's Fear & Greed Index — a daily 0–100 sentiment "
        "score blending price momentum, volatility, breadth, put/call ratios, and "
        "safe-haven demand. We buy the ticker when sentiment falls below "
        "buy_below (default 25, 'extreme fear') and exit to cash when it climbs "
        "above exit_above (default 75, 'extreme greed'). The premise is that "
        "crowd extremes mark turning points. Two data sources are available "
        "(picked via --fg-source): 'cnn' uses the live CNN endpoint (~5.5 years "
        "of history, includes component sub-indices), 'whit3rabbit' uses a "
        "community CSV mirror reaching back to 2011-01-03 (headline score only)."
    )
    data_requirements = frozenset({"prices", "fear_greed"})

    def orders(
        self,
        context: dict[str, pd.DataFrame],
        total_budget: float,
        params: dict[str, Any],
    ) -> list[Order]:
        prices = context["prices"]
        fg = context["fear_greed"]
        if prices.empty:
            return []

        buy_below = float(params.get("buy_below", 25.0))
        exit_above = float(params.get("exit_above", 75.0))
        index_col = params.get("index_type", "fear_greed")
        if not (0 < buy_below < exit_above < 100):
            raise ValueError(
                f"Need 0 < buy_below < exit_above < 100; got {buy_below}, {exit_above}"
            )
        if index_col not in fg.columns:
            raise ValueError(
                f"Index column {index_col!r} not in F&G data; available: {list(fg.columns)}"
            )

        signal = fg[index_col]

        # Day 0 default: stay in cash and wait for the first fear signal. Override with
        # start_in_market=true to deposit-and-buy on day 0.
        start_in_market = bool(params.get("start_in_market", False))
        orders: list[Order] = [
            Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=total_budget)
        ]
        if not start_in_market:
            orders.append(Order(date=prices.index[0], action=Action.SELL_ALL))
        in_position = start_in_market

        for i in range(1, len(prices)):
            day = prices.index[i]
            value = signal.iloc[i]
            if pd.isna(value):
                continue
            if not in_position and value < buy_below:
                orders.append(Order(date=day, action=Action.BUY_ALL_CASH))
                in_position = True
            elif in_position and value > exit_above:
                orders.append(Order(date=day, action=Action.SELL_ALL))
                in_position = False
        return orders
