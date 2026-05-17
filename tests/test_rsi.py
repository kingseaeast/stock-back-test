"""Tests for the RSI strategy and the Wilder RSI helper."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import Action
from src.strategies.rsi import RSI, wilder_rsi

from .conftest import make_prices


class TestWilderRsi:
    def test_period_floor(self):
        s = pd.Series([1.0, 2.0, 3.0])
        with pytest.raises(ValueError):
            wilder_rsi(s, period=1)

    def test_warmup_is_nan(self):
        s = pd.Series([100.0 + i for i in range(20)])
        r = wilder_rsi(s, period=14)
        # First `period` bars (incl. the diff NaN) should be NaN
        assert r.iloc[:14].isna().all()
        assert not pd.isna(r.iloc[14])

    def test_monotonic_up_reaches_100(self):
        # Strictly increasing prices -> all gains, no losses -> RSI = 100.
        s = pd.Series([100.0 + i for i in range(50)])
        r = wilder_rsi(s, period=14)
        # Once warmed up, RSI should be 100
        assert r.iloc[-1] == pytest.approx(100.0)

    def test_monotonic_down_reaches_zero(self):
        s = pd.Series([200.0 - i for i in range(50)])
        r = wilder_rsi(s, period=14)
        assert r.iloc[-1] == pytest.approx(0.0)

    def test_flat_is_fifty(self):
        s = pd.Series([100.0] * 50)
        r = wilder_rsi(s, period=14)
        # Flat -> avg_gain = avg_loss = 0 -> defined as 50 by convention.
        assert r.iloc[-1] == pytest.approx(50.0)


class TestRSIStrategy:
    def test_declares_prices_requirement(self):
        assert RSI.data_requirements == frozenset({"prices"})

    def test_param_validation(self, linear_prices):
        with pytest.raises(ValueError, match="oversold"):
            RSI().orders(
                {"prices": linear_prices}, total_budget=10_000,
                params={"oversold": 50, "overbought": 50},
            )

    def test_default_is_invested_on_day_zero(self, linear_prices):
        orders = RSI().orders(
            {"prices": linear_prices}, total_budget=10_000, params={},
        )
        # First order should be the day-0 deposit-and-buy.
        assert orders[0].action == Action.DEPOSIT_AND_BUY
        assert orders[0].date == linear_prices.index[0]
        assert orders[0].amount == 10_000.0

    def test_start_in_cash_emits_immediate_sell(self, linear_prices):
        orders = RSI().orders(
            {"prices": linear_prices}, total_budget=10_000,
            params={"start_in_cash": True},
        )
        assert orders[0].action == Action.DEPOSIT_AND_BUY
        assert orders[1].action == Action.SELL_ALL
        assert orders[1].date == linear_prices.index[0]

    def test_signals_alternate_buy_then_sell(self):
        """A V-shape strong enough to trigger both oversold and overbought."""
        # Crash 200 -> 50 (RSI tanks), then rip 50 -> 200 (RSI explodes).
        down = [200.0 - i * (150.0 / 49) for i in range(50)]
        up = [50.0 + i * (150.0 / 49) for i in range(50)]
        prices = make_prices(down + up)

        orders = RSI().orders(
            {"prices": prices}, total_budget=10_000,
            params={"period": 14, "oversold": 30, "overbought": 70, "start_in_cash": True},
        )
        # Skip the day-0 deposit + sell. Remaining orders should alternate buy/sell.
        signal_orders = [o for o in orders if o.date != prices.index[0]]
        assert len(signal_orders) >= 2
        assert signal_orders[0].action == Action.BUY_ALL_CASH  # oversold during crash
        assert signal_orders[1].action == Action.SELL_ALL      # overbought during rip
