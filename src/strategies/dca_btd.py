"""DCA + Buy The Dip.

Splits `total_budget` into:
  - a regular DCA portion (default 80%) spread evenly on cadence;
  - a dip reserve (default 20%) deployed in chunks whenever price closes
    `dip_threshold_pct` below its trailing `dip_lookback`-day high.

The reserve is split into `dip_buys` equal chunks (default 4), each fired the
first time a dip qualifies after the previous chunk was deployed. If the budget
window ends with reserve unused, that cash sits.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order
from .dca import _CADENCE_FREQ


class DCABTD:
    name = "dca_btd"
    description = (
        "DCA with a 'buy the dip' reserve. Most of the budget contributes on the "
        "regular cadence (default 80%); the rest waits in cash and gets deployed "
        "in chunks whenever the price closes meaningfully below its recent high "
        "(default: 10% below the trailing 90-day high). Tries to capture the "
        "extra return from buying drawdowns without abandoning the discipline of "
        "regular contributions. A single drawdown only fires the reserve once — "
        "the price must recover above the threshold before the next dip-buy can arm."
    )
    data_requirements = frozenset({"prices"})

    def orders(
        self,
        context: dict[str, pd.DataFrame],
        total_budget: float,
        params: dict[str, Any],
    ) -> list[Order]:
        prices = context["prices"]
        if prices.empty:
            return []

        cadence = params.get("cadence", "monthly")
        if cadence not in _CADENCE_FREQ:
            raise ValueError(
                f"Unknown cadence {cadence!r}. Use one of {sorted(_CADENCE_FREQ)}"
            )
        dip_reserve_pct = float(params.get("dip_reserve_pct", 0.20))
        dip_threshold_pct = float(params.get("dip_threshold_pct", 0.10))
        dip_lookback = int(params.get("dip_lookback", 90))
        dip_buys = int(params.get("dip_buys", 4))
        if not (0.0 <= dip_reserve_pct < 1.0):
            raise ValueError("dip_reserve_pct must be in [0, 1)")
        if dip_threshold_pct <= 0:
            raise ValueError("dip_threshold_pct must be > 0")
        if dip_buys < 1:
            raise ValueError("dip_buys must be >= 1")

        dca_total = total_budget * (1 - dip_reserve_pct)
        reserve_total = total_budget * dip_reserve_pct
        per_dip_buy = reserve_total / dip_buys if dip_buys > 0 else 0.0

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

        # Dip detection: at each bar, compare close to the trailing dip_lookback-day
        # max (excluding today). Once a dip fires, refractory until the price recovers
        # back above the dip threshold, so we don't spend all reserves on consecutive
        # down days in a single drawdown.
        close = prices["adj_close"].astype(float)
        trailing_max = close.shift(1).rolling(window=dip_lookback, min_periods=1).max()
        threshold_price = trailing_max * (1 - dip_threshold_pct)

        reserve_remaining = reserve_total
        in_dip = False  # are we currently below the dip threshold?
        for i in range(1, len(prices)):
            if reserve_remaining <= 0:
                break
            day = prices.index[i]
            below_threshold = close.iloc[i] <= threshold_price.iloc[i]
            if below_threshold and not in_dip:
                amount = min(per_dip_buy, reserve_remaining)
                orders.append(
                    Order(date=day, action=Action.DEPOSIT_AND_BUY, amount=amount)
                )
                reserve_remaining -= amount
                in_dip = True
            elif not below_threshold:
                in_dip = False

        orders.sort(key=lambda o: o.date)
        return orders
