"""DCA with sentiment-driven trim-and-deploy.

Contributes on the regular DCA cadence. Whenever CNN's Fear & Greed index
crosses above `greed_threshold` (default 75 = 'extreme greed') we sell
`sell_pct` (default 25%) of current holdings and park the cash in a war
chest. Whenever F&G crashes below `fear_threshold` (default 25 = 'extreme
fear') we deploy the entire war chest back into the position.

Each greed/fear episode fires once — sentiment must cross back through
the neutral zone (i.e. recover above fear_threshold after a fear episode,
or fall below greed_threshold after a greed episode) before the same side
can re-arm.

Differs from dca_fg in that the "reserve" isn't fixed up front; it's
built dynamically by trimming at the top.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order
from .dca import _CADENCE_FREQ


class DCAFearGreedRebalance:
    name = "dca_fg_rebalance"
    description = (
        "DCA with sentiment-driven trim-and-deploy. Contributes on the regular "
        "cadence; when CNN's Fear & Greed climbs above greed_threshold (default "
        "75, 'extreme greed') it sells a sell_pct slice of current holdings "
        "(default 25%) into a war chest; when sentiment crashes below "
        "fear_threshold (default 25) it deploys the entire war chest back into "
        "the position. Buys the dip; trims the top. Each greed/fear episode "
        "fires once — sentiment must cross back through the neutral zone before "
        "re-arming."
    )
    data_requirements = frozenset({"prices", "fear_greed"})
    param_schema: list[dict] = [
        {
            "name": "cadence", "type": "select", "default": "monthly",
            "options": ["weekly", "biweekly", "monthly"],
            "label": "Contribution cadence",
        },
        {
            "name": "greed_threshold", "type": "number", "default": 75,
            "min": 51, "max": 99, "step": 1,
            "label": "Greed threshold (trim above)",
        },
        {
            "name": "fear_threshold", "type": "number", "default": 25,
            "min": 1, "max": 49, "step": 1,
            "label": "Fear threshold (deploy below)",
        },
        {
            "name": "sell_pct", "type": "number", "default": 0.25,
            "min": 0.05, "max": 0.95, "step": 0.05,
            "label": "Fraction of holdings to sell on greed",
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
        greed_threshold = float(params.get("greed_threshold", 75))
        fear_threshold = float(params.get("fear_threshold", 25))
        sell_pct = float(params.get("sell_pct", 0.25))
        index_col = params.get("index_type", "fear_greed")

        if not (0 < fear_threshold < greed_threshold < 100):
            raise ValueError(
                f"Need 0 < fear_threshold < greed_threshold < 100; got "
                f"{fear_threshold}, {greed_threshold}"
            )
        if not (0 < sell_pct < 1):
            raise ValueError("sell_pct must be in (0, 1)")
        if index_col not in fg.columns:
            raise ValueError(
                f"Index column {index_col!r} not in F&G data; available: {list(fg.columns)}"
            )

        # Plain DCA contributions on cadence — full budget, no held-back reserve.
        period_starts = pd.date_range(
            start=prices.index[0], end=prices.index[-1], freq=_CADENCE_FREQ[cadence],
        )
        contribution_dates: list[pd.Timestamp] = []
        for ps in period_starts:
            idx = prices.index.searchsorted(ps, side="left")
            if idx < len(prices.index):
                contribution_dates.append(prices.index[idx])
        contribution_dates = sorted(set(contribution_dates))
        per_contribution = (
            total_budget / len(contribution_dates) if contribution_dates else 0.0
        )
        orders: list[Order] = [
            Order(date=d, action=Action.DEPOSIT_AND_BUY, amount=per_contribution)
            for d in contribution_dates
        ]

        # Sentiment-driven trim/deploy. Two refractory flags (one per side) so a
        # sustained greed or fear episode only fires once.
        signal = fg[index_col]
        in_greed = False
        in_fear = False
        for i in range(1, len(prices)):
            day = prices.index[i]
            value = signal.iloc[i]
            if pd.isna(value):
                continue
            if value > greed_threshold:
                if not in_greed:
                    orders.append(Order(date=day, action=Action.SELL_FRACTION, amount=sell_pct))
                    in_greed = True
                # If already in greed, do nothing; one trim per episode.
                in_fear = False  # leaving any fear regime resets fear side
            elif value < fear_threshold:
                if not in_fear:
                    orders.append(Order(date=day, action=Action.DEPLOY_RESERVE))
                    in_fear = True
                in_greed = False
            else:
                # Neutral zone: both sides re-arm
                in_greed = False
                in_fear = False

        orders.sort(key=lambda o: o.date)
        return orders
