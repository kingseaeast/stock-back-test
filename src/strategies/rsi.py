"""RSI buy/sell — all-in / all-out on classic Wilder RSI thresholds.

Long-only contrarian: buy when RSI drops below `oversold`, sell when it climbs
above `overbought`. Starts in cash; flips between fully invested and fully cash.

Uses Wilder's smoothing (the standard for RSI), implemented as an EMA with
alpha = 1/period.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .base import Action, Order


def wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder-smoothed RSI on a close-price series. NaN until `period` bars of history."""
    if period < 2:
        raise ValueError("RSI period must be >= 2")
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing = EMA with alpha = 1/period; min_periods=period gives us NaN warm-up.
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    # When avg_loss is 0 and avg_gain > 0, RS is +inf -> RSI = 100. Backfill that.
    rsi = rsi.where(avg_loss != 0, other=100.0)
    # When both are zero (flat), RSI is undefined; convention is 50.
    flat = (avg_gain == 0) & (avg_loss == 0)
    rsi = rsi.where(~flat, other=50.0)
    return rsi


class RSI:
    name = "rsi"
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

        period = int(params.get("period", 14))
        oversold = float(params.get("oversold", 30))
        overbought = float(params.get("overbought", 70))
        if not (0 < oversold < overbought < 100):
            raise ValueError(
                f"Need 0 < oversold < overbought < 100; got {oversold}, {overbought}"
            )

        rsi = wilder_rsi(prices["adj_close"].astype(float), period)

        # Day 0 default: enter the market (deposit + buy). Pass start_in_cash=true to
        # wait for the first oversold signal instead.
        start_in_cash = bool(params.get("start_in_cash", False))
        orders: list[Order] = [
            Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=total_budget)
        ]
        if start_in_cash:
            orders.append(Order(date=prices.index[0], action=Action.SELL_ALL))
        in_position = not start_in_cash
        # Iterate, looking only at RSI values known at each bar (no look-ahead — RSI
        # at index t is computed from closes up to and including t, engine executes
        # signals on the *next* bar).
        for i in range(1, len(prices)):
            day = prices.index[i]
            rsi_value = rsi.iloc[i]
            if pd.isna(rsi_value):
                continue
            if in_position and rsi_value > overbought:
                orders.append(Order(date=day, action=Action.SELL_ALL))
                in_position = False
            elif not in_position and rsi_value < oversold:
                orders.append(Order(date=day, action=Action.BUY_ALL_CASH))
                in_position = True
        return orders
