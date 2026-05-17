"""Tests for DCA + Fear-Greed."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import Action
from src.strategies.dca_fg import DCAFearGreed

from .conftest import make_prices


def _fg(values: list[float], index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"fear_greed": values}, index=index)


class TestDCAFearGreed:
    def test_declares_both_data_requirements(self):
        assert DCAFearGreed.data_requirements == frozenset({"prices", "fear_greed"})

    def test_split_default_is_80_20_when_no_fear(self):
        """Flat prices, F&G stable above threshold → only DCA contributions fire."""
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg = _fg([50.0] * 252, prices.index)
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        # Only DCA contributions (80% of 10k = 8000), no fear-buys
        deposited = sum(o.amount for o in orders if o.action == Action.DEPOSIT_AND_BUY)
        assert deposited == pytest.approx(8_000.0)

    def test_extreme_fear_triggers_reserve_buy(self):
        """F&G dropping below threshold fires one reserve chunk."""
        prices = make_prices([100.0] * 252, start="2020-01-02")
        # Stable greed for half a year, then extreme fear for the rest
        fg_values = [50.0] * 126 + [15.0] * 126
        fg = _fg(fg_values, prices.index)
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly", "fear_threshold": 25, "fear_buys": 4},
        )
        # Per-fear-buy is 20%/4 = 500. Single fear episode → exactly one $500 deposit.
        fear_buys = [o for o in orders if o.amount == pytest.approx(500.0)]
        assert len(fear_buys) == 1

    def test_fear_refractory_single_episode(self):
        """Sustained fear should fire only once, not on every below-threshold day."""
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg = _fg([15.0] * 252, prices.index)  # extreme fear all year
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly", "fear_threshold": 25, "fear_buys": 4},
        )
        fear_buys = [o for o in orders if o.amount == pytest.approx(500.0)]
        assert len(fear_buys) == 1

    def test_repeated_fear_episodes_fire_multiple_reserve_buys(self):
        """F&G must recover above threshold to re-arm; then drop fires again."""
        # 3 fear/recovery cycles
        block = ([50.0] * 30 + [15.0] * 20) * 3 + [50.0] * 30
        prices = make_prices([100.0] * len(block), start="2020-01-02")
        fg = _fg(block, prices.index)
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly", "fear_threshold": 25, "fear_buys": 4},
        )
        fear_buys = [o for o in orders if o.amount == pytest.approx(500.0)]
        assert len(fear_buys) == 3

    def test_param_validation(self):
        prices = make_prices([100.0] * 30)
        fg = _fg([50.0] * 30, prices.index)
        ctx = {"prices": prices, "fear_greed": fg}
        with pytest.raises(ValueError, match="fear_reserve_pct"):
            DCAFearGreed().orders(ctx, 10_000, params={"fear_reserve_pct": 1.5})
        with pytest.raises(ValueError, match="fear_threshold"):
            DCAFearGreed().orders(ctx, 10_000, params={"fear_threshold": 0})
        with pytest.raises(ValueError, match="fear_buys"):
            DCAFearGreed().orders(ctx, 10_000, params={"fear_buys": 0})
        with pytest.raises(ValueError, match="Unknown cadence"):
            DCAFearGreed().orders(ctx, 10_000, params={"cadence": "yearly"})
        with pytest.raises(ValueError, match="not in F&G data"):
            DCAFearGreed().orders(ctx, 10_000, params={"index_type": "bogus"})

    def test_orders_are_chronological(self):
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg_values = [50.0] * 100 + [15.0] * 50 + [50.0] * 102
        fg = _fg(fg_values, prices.index)
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        dates = [o.date for o in orders]
        assert dates == sorted(dates)

    def test_total_does_not_exceed_budget(self):
        prices = make_prices([100.0] * 252, start="2020-01-02")
        # Many fear episodes so reserve fully deploys
        block = ([50.0] * 5 + [15.0] * 5) * 25 + [50.0] * 2
        fg = _fg(block, prices.index)
        orders = DCAFearGreed().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly", "fear_buys": 4},
        )
        total = sum(o.amount for o in orders)
        # DCA total (8000) + fully deployed reserve (2000) = 10000
        assert total <= 10_000.0 + 1e-6
