"""Tests for the F&G strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import Action
from src.strategies.fear_greed import FearGreed

from .conftest import make_prices


def _fg_frame(values: list[float], index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"fear_greed": values}, index=index)


class TestFearGreedStrategy:
    def test_declares_both_data_requirements(self):
        assert FearGreed.data_requirements == frozenset({"prices", "fear_greed"})

    def test_param_validation(self):
        prices = make_prices([100.0] * 30)
        fg = _fg_frame([50.0] * 30, prices.index)
        ctx = {"prices": prices, "fear_greed": fg}
        with pytest.raises(ValueError, match="buy_below"):
            FearGreed().orders(ctx, 10_000, params={"buy_below": 80, "exit_above": 20})
        with pytest.raises(ValueError, match="not in F&G data"):
            FearGreed().orders(ctx, 10_000, params={"index_type": "nope"})

    def test_default_starts_in_cash(self):
        """Day 0: deposit-and-buy + immediate sell so portfolio is cash-only."""
        prices = make_prices([100.0] * 30)
        fg = _fg_frame([50.0] * 30, prices.index)
        orders = FearGreed().orders(
            {"prices": prices, "fear_greed": fg}, 10_000, params={},
        )
        assert orders[0].action == Action.DEPOSIT_AND_BUY
        assert orders[1].action == Action.SELL_ALL
        assert orders[0].date == prices.index[0]
        assert orders[1].date == prices.index[0]

    def test_fear_below_threshold_triggers_buy(self):
        # Day 0..9: F&G=50 (no signal). Day 10: F&G=20 (extreme fear, buy).
        prices = make_prices([100.0] * 30)
        fg_values = [50.0] * 10 + [20.0] + [50.0] * 19
        fg = _fg_frame(fg_values, prices.index)
        orders = FearGreed().orders(
            {"prices": prices, "fear_greed": fg}, 10_000,
            params={"buy_below": 25, "exit_above": 75},
        )
        signal_orders = [o for o in orders if o.date != prices.index[0]]
        assert len(signal_orders) == 1
        assert signal_orders[0].action == Action.BUY_ALL_CASH
        assert signal_orders[0].date == prices.index[10]

    def test_greed_above_threshold_triggers_sell_after_buy(self):
        # Sequence of fear -> greed.
        prices = make_prices([100.0] * 30)
        fg_values = [50.0] * 5 + [20.0] * 5 + [50.0] * 5 + [85.0] * 15
        fg = _fg_frame(fg_values, prices.index)
        orders = FearGreed().orders(
            {"prices": prices, "fear_greed": fg}, 10_000,
            params={"buy_below": 25, "exit_above": 75},
        )
        signal_orders = [o for o in orders if o.date != prices.index[0]]
        actions = [o.action for o in signal_orders]
        # First a BUY when F&G drops below 25, then a SELL when it climbs above 75.
        assert actions[0] == Action.BUY_ALL_CASH
        assert Action.SELL_ALL in actions

    def test_start_in_market_skips_initial_sell(self):
        prices = make_prices([100.0] * 30)
        fg = _fg_frame([50.0] * 30, prices.index)
        orders = FearGreed().orders(
            {"prices": prices, "fear_greed": fg}, 10_000,
            params={"start_in_market": True},
        )
        # No SELL_ALL on day 0
        day0 = [o for o in orders if o.date == prices.index[0]]
        assert len(day0) == 1
        assert day0[0].action == Action.DEPOSIT_AND_BUY

    def test_nan_signals_skipped(self):
        """If the F&G value is NaN on a given day, no signal fires."""
        prices = make_prices([100.0] * 30)
        fg_values: list[float] = [float("nan")] * 30
        fg = _fg_frame(fg_values, prices.index)
        orders = FearGreed().orders(
            {"prices": prices, "fear_greed": fg}, 10_000, params={},
        )
        # Only the day-0 deposit + sell; no further signals.
        signal_orders = [o for o in orders if o.date != prices.index[0]]
        assert signal_orders == []
