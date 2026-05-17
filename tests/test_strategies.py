"""Tests for strategy order schedules.

These check what each strategy *intends* to do; the engine tests verify
the execution math separately.
"""

from __future__ import annotations

import pytest

from src.strategies import REGISTRY, get
from src.strategies.base import Action
from src.strategies.buy_hold import BuyHold
from src.strategies.dca import DCA

from .conftest import make_prices


class TestRegistry:
    def test_contains_v1_strategies(self):
        assert set(REGISTRY) >= {"buy_hold", "dca"}

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            get("does_not_exist")

    def test_every_strategy_has_a_meaningful_description(self):
        """Each registered strategy must carry a plain-English description
        that gets rendered in reports and surfaced to the AI agent."""
        for name, cls in REGISTRY.items():
            desc = getattr(cls, "description", None)
            assert isinstance(desc, str) and len(desc) >= 40, (
                f"{name!r} needs a description ≥40 chars (got {desc!r})"
            )

    def test_every_strategy_has_a_valid_param_schema(self):
        """Every strategy must declare param_schema (may be empty list).
        Each entry must have name, type, default, label and type-appropriate fields."""
        valid_types = {"number", "select", "boolean"}
        for name, cls in REGISTRY.items():
            schema = getattr(cls, "param_schema", None)
            assert isinstance(schema, list), f"{name}.param_schema must be a list"
            for entry in schema:
                for required in ("name", "type", "default", "label"):
                    assert required in entry, (
                        f"{name}.param_schema entry missing {required!r}: {entry}"
                    )
                assert entry["type"] in valid_types, (
                    f"{name}.param_schema entry has unknown type {entry['type']!r}"
                )
                if entry["type"] == "number":
                    for required in ("min", "max", "step"):
                        assert required in entry, (
                            f"{name}.param_schema number entry missing {required!r}: {entry}"
                        )
                if entry["type"] == "select":
                    assert "options" in entry and entry["options"], (
                        f"{name}.param_schema select entry needs non-empty options"
                    )
                    assert entry["default"] in entry["options"], (
                        f"{name}.param_schema default {entry['default']!r} not in options"
                    )


class TestBuyHold:
    def test_single_order_on_first_day(self, linear_prices):
        orders = BuyHold().orders({"prices": linear_prices}, total_budget=10_000, params={})
        assert len(orders) == 1
        assert orders[0].date == linear_prices.index[0]
        assert orders[0].action == Action.DEPOSIT_AND_BUY
        assert orders[0].amount == 10_000.0

    def test_empty_prices_no_orders(self):
        empty = make_prices([])
        assert BuyHold().orders({"prices": empty}, total_budget=10_000, params={}) == []

    def test_declares_prices_requirement(self):
        assert BuyHold.data_requirements == frozenset({"prices"})


class TestDCA:
    def test_monthly_cadence_count(self):
        # 6 months of business days ~= 130 bdays
        prices = make_prices([100.0] * 130, start="2020-01-02")
        orders = DCA().orders({"prices": prices}, total_budget=6_000, params={"cadence": "monthly"})
        # Jan, Feb, Mar, Apr, May, Jun first trading days = 6 contributions
        assert len(orders) == 6
        for o in orders:
            assert o.action == Action.DEPOSIT_AND_BUY
            assert o.amount == pytest.approx(1_000.0)

    def test_contributions_sum_to_budget(self):
        prices = make_prices([100.0] * 252, start="2020-01-02")  # ~1 year
        orders = DCA().orders({"prices": prices}, total_budget=10_000, params={"cadence": "monthly"})
        total = sum(o.amount for o in orders)
        assert total == pytest.approx(10_000.0)

    def test_default_cadence_is_monthly(self):
        prices = make_prices([100.0] * 130)
        default = DCA().orders({"prices": prices}, total_budget=6_000, params={})
        monthly = DCA().orders({"prices": prices}, total_budget=6_000, params={"cadence": "monthly"})
        assert len(default) == len(monthly)
        assert [o.date for o in default] == [o.date for o in monthly]

    def test_weekly_more_frequent_than_monthly(self):
        prices = make_prices([100.0] * 130)
        weekly = DCA().orders({"prices": prices}, total_budget=6_000, params={"cadence": "weekly"})
        monthly = DCA().orders({"prices": prices}, total_budget=6_000, params={"cadence": "monthly"})
        assert len(weekly) > len(monthly)

    def test_unknown_cadence_raises(self, linear_prices):
        with pytest.raises(ValueError, match="Unknown cadence"):
            DCA().orders({"prices": linear_prices}, total_budget=10_000, params={"cadence": "yearly"})

    def test_orders_land_on_trading_days(self, linear_prices):
        orders = DCA().orders({"prices": linear_prices}, total_budget=10_000, params={"cadence": "monthly"})
        for o in orders:
            assert o.date in linear_prices.index
