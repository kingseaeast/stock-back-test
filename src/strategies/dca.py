"""Dollar-cost averaging: split total_budget into equal cadence contributions."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order


_CADENCE_FREQ = {
    "weekly": "W-MON",
    "biweekly": "2W-MON",
    "monthly": "MS",   # month start
}


class DCA:
    name = "dca"
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

        period_starts = pd.date_range(
            start=prices.index[0],
            end=prices.index[-1],
            freq=_CADENCE_FREQ[cadence],
        )
        contribution_dates = []
        trading_days = prices.index
        for ps in period_starts:
            idx = trading_days.searchsorted(ps, side="left")
            if idx < len(trading_days):
                contribution_dates.append(trading_days[idx])

        contribution_dates = sorted(set(contribution_dates))
        if not contribution_dates:
            return []

        per_contribution = total_budget / len(contribution_dates)
        return [
            Order(date=d, action=Action.DEPOSIT_AND_BUY, amount=per_contribution)
            for d in contribution_dates
        ]
