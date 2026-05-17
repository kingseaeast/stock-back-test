"""DCA + Buy The Fear.

Splits `total_budget` into:
  - a regular DCA portion (default 80%) spread evenly on cadence;
  - a fear reserve (default 20%) deployed in chunks whenever CNN's Fear &
    Greed index closes below `fear_threshold` (default 25 = 'extreme fear').

A single fear episode only fires the reserve once — the index must recover
above the threshold before the next fear-buy can arm.

Sister to `dca_btd`, but uses crowd sentiment as the dip trigger instead of
price drawdown. Combines DCA's discipline with a contrarian boost on
sentiment crashes.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order
from .dca import _CADENCE_FREQ


class DCAFearGreed:
    name = "dca_fg"
    description = (
        "DCA + 'buy the fear'. Most of the budget contributes on the regular "
        "cadence (default 80%); the rest waits in cash and deploys in chunks "
        "whenever CNN's Fear & Greed index closes below the fear_threshold "
        "(default 25, 'extreme fear'). Combines DCA's discipline with a "
        "contrarian boost on sentiment crashes. A single fear episode only "
        "fires the reserve once — the index must recover above the threshold "
        "before the next fear-buy can arm. Requires F&G data; pick the source "
        "via --fg-source."
    )
    data_requirements = frozenset({"prices", "fear_greed"})
    param_schema: list[dict] = [
        {
            "name": "cadence", "type": "select", "default": "monthly",
            "options": ["weekly", "biweekly", "monthly"],
            "label": "Contribution cadence",
        },
        {
            "name": "fear_reserve_pct", "type": "number", "default": 0.20,
            "min": 0.0, "max": 0.95, "step": 0.05,
            "label": "Fear reserve (fraction of budget)",
        },
        {
            "name": "fear_threshold", "type": "number", "default": 25,
            "min": 1, "max": 49, "step": 1,
            "label": "Fear threshold (buy below)",
        },
        {
            "name": "fear_buys", "type": "number", "default": 4,
            "min": 1, "max": 20, "step": 1,
            "label": "Number of fear buys",
        },
        {
            "name": "index_type", "type": "select", "default": "fear_greed",
            "options": [
                "fear_greed", "market_momentum_sp500", "stock_price_strength",
                "stock_price_breadth", "put_call_options", "market_volatility_vix",
                "safe_haven_demand", "junk_bond_demand",
            ],
            "label": "F&G index/component",
            "help": "Sub-indices only available with --fg-source cnn",
        },
    ]

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

        cadence = params.get("cadence", "monthly")
        if cadence not in _CADENCE_FREQ:
            raise ValueError(
                f"Unknown cadence {cadence!r}. Use one of {sorted(_CADENCE_FREQ)}"
            )
        fear_reserve_pct = float(params.get("fear_reserve_pct", 0.20))
        fear_threshold = float(params.get("fear_threshold", 25))
        fear_buys = int(params.get("fear_buys", 4))
        index_col = params.get("index_type", "fear_greed")

        if not (0.0 <= fear_reserve_pct < 1.0):
            raise ValueError("fear_reserve_pct must be in [0, 1)")
        if not (0 < fear_threshold < 100):
            raise ValueError("fear_threshold must be in (0, 100)")
        if fear_buys < 1:
            raise ValueError("fear_buys must be >= 1")
        if index_col not in fg.columns:
            raise ValueError(
                f"Index column {index_col!r} not in F&G data; available: {list(fg.columns)}"
            )

        dca_total = total_budget * (1 - fear_reserve_pct)
        reserve_total = total_budget * fear_reserve_pct
        per_fear_buy = reserve_total / fear_buys if fear_buys > 0 else 0.0

        # DCA contributions: same logic as plain DCA but scaled to dca_total.
        period_starts = pd.date_range(
            start=prices.index[0], end=prices.index[-1], freq=_CADENCE_FREQ[cadence],
        )
        contribution_dates: list[pd.Timestamp] = []
        for ps in period_starts:
            idx = prices.index.searchsorted(ps, side="left")
            if idx < len(prices.index):
                contribution_dates.append(prices.index[idx])
        contribution_dates = sorted(set(contribution_dates))
        per_contribution = dca_total / len(contribution_dates) if contribution_dates else 0.0
        orders: list[Order] = [
            Order(date=d, action=Action.DEPOSIT_AND_BUY, amount=per_contribution)
            for d in contribution_dates
        ]

        # Fear detection: F&G aligned to trading days. Below threshold = fear.
        # Refractory state: once we fire, F&G must recover above threshold before
        # the next fear-buy can arm.
        signal = fg[index_col]
        reserve_remaining = reserve_total
        in_fear = False
        for i in range(1, len(prices)):
            if reserve_remaining <= 0:
                break
            day = prices.index[i]
            value = signal.iloc[i]
            if pd.isna(value):
                continue
            below_threshold = value < fear_threshold
            if below_threshold and not in_fear:
                amount = min(per_fear_buy, reserve_remaining)
                orders.append(
                    Order(date=day, action=Action.DEPOSIT_AND_BUY, amount=amount)
                )
                reserve_remaining -= amount
                in_fear = True
            elif not below_threshold:
                in_fear = False

        orders.sort(key=lambda o: o.date)
        return orders
