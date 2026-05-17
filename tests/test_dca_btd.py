"""Tests for DCA+BTD."""

from __future__ import annotations

import pytest

from src.strategies.base import Action
from src.strategies.dca_btd import DCABTD

from .conftest import make_prices


class TestDCABTD:
    def test_declares_prices_requirement(self):
        assert DCABTD.data_requirements == frozenset({"prices"})

    def test_split_default_is_80_20(self):
        """At flat prices with no dips, 80% deploys via DCA, 20% sits in reserve."""
        prices = make_prices([100.0] * 252, start="2020-01-02")  # 1 year, flat
        orders = DCABTD().orders(
            {"prices": prices}, total_budget=10_000,
            params={"cadence": "monthly"},  # defaults: 20% reserve, no dips trigger
        )
        dca_total = sum(o.amount for o in orders if o.action == Action.DEPOSIT_AND_BUY)
        # No dips at flat prices, so only DCA orders -> 80% of 10k
        assert dca_total == pytest.approx(8_000.0)

    def test_dip_triggers_reserve_buy(self):
        """A 15% drawdown triggers a buy because default threshold is 10%."""
        # Stable for a year, then a big drop on day 252.
        prices_values = [100.0] * 252 + [85.0] * 30  # 15% drop, stays down
        prices = make_prices(prices_values, start="2020-01-02")
        orders = DCABTD().orders(
            {"prices": prices}, total_budget=10_000,
            params={"cadence": "monthly", "dip_threshold_pct": 0.10, "dip_buys": 4},
        )
        # 80%/12months ≈ 666 per DCA contribution; reserve buys are 20%/4 = 500 each.
        dip_amounts = [
            o.amount for o in orders
            if o.action == Action.DEPOSIT_AND_BUY and o.amount == pytest.approx(500.0)
        ]
        assert len(dip_amounts) >= 1, "Expected at least one $500 reserve buy on the dip"

    def test_dip_refractory_single_drawdown(self):
        """A single drawdown that stays below threshold should fire only once
        (not repeatedly on consecutive down days)."""
        prices_values = [100.0] * 252 + [85.0] * 30
        prices = make_prices(prices_values, start="2020-01-02")
        orders = DCABTD().orders(
            {"prices": prices}, total_budget=10_000,
            params={"cadence": "monthly", "dip_threshold_pct": 0.10, "dip_buys": 4},
        )
        dip_amounts = [
            o.amount for o in orders
            if o.action == Action.DEPOSIT_AND_BUY and o.amount == pytest.approx(500.0)
        ]
        # Single drawdown, no recovery -> exactly one reserve fire.
        assert len(dip_amounts) == 1

    def test_repeated_drawdowns_fire_multiple_reserve_buys(self):
        """Price has to recover above the threshold before re-arming, then dip again."""
        # Three V-shapes: down 15%, back up, down 15%, back up, down 15%
        block = [100.0] * 100 + [85.0] * 10 + [100.0] * 100 + [85.0] * 10 + [100.0] * 100 + [85.0] * 10
        prices = make_prices(block, start="2020-01-02")
        orders = DCABTD().orders(
            {"prices": prices}, total_budget=10_000,
            params={"cadence": "monthly", "dip_threshold_pct": 0.10, "dip_buys": 4},
        )
        dip_amounts = [
            o.amount for o in orders
            if o.action == Action.DEPOSIT_AND_BUY and o.amount == pytest.approx(500.0)
        ]
        assert len(dip_amounts) == 3

    def test_param_validation(self):
        prices = make_prices([100.0] * 30)
        with pytest.raises(ValueError, match="dip_reserve_pct"):
            DCABTD().orders(
                {"prices": prices}, total_budget=10_000, params={"dip_reserve_pct": 1.5},
            )
        with pytest.raises(ValueError, match="dip_threshold_pct"):
            DCABTD().orders(
                {"prices": prices}, total_budget=10_000, params={"dip_threshold_pct": 0},
            )
        with pytest.raises(ValueError, match="dip_buys"):
            DCABTD().orders(
                {"prices": prices}, total_budget=10_000, params={"dip_buys": 0},
            )
        with pytest.raises(ValueError, match="Unknown cadence"):
            DCABTD().orders(
                {"prices": prices}, total_budget=10_000, params={"cadence": "yearly"},
            )

    def test_orders_are_chronological(self):
        """Engine expects sorted orders; DCA + BTD interleaves chronologically."""
        prices_values = [100.0] * 100 + [80.0] * 5 + [100.0] * 100
        prices = make_prices(prices_values, start="2020-01-02")
        orders = DCABTD().orders(
            {"prices": prices}, total_budget=10_000, params={"cadence": "monthly"},
        )
        dates = [o.date for o in orders]
        assert dates == sorted(dates)
