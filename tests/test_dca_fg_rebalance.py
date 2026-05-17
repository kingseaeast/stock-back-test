"""Tests for the trim-on-greed / deploy-on-fear strategy."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import Action
from src.strategies.dca_fg_rebalance import DCAFearGreedRebalance

from .conftest import make_prices


def _fg(values: list[float], index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"fear_greed": values}, index=index)


class TestDCAFearGreedRebalance:
    def test_declares_both_data_requirements(self):
        assert DCAFearGreedRebalance.data_requirements == frozenset({"prices", "fear_greed"})

    def test_no_signals_when_neutral(self):
        """F&G stable in neutral zone → only DCA contributions, no trim/deploy."""
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg = _fg([50.0] * 252, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        kinds = {o.action for o in orders}
        assert kinds == {Action.DEPOSIT_AND_BUY}

    def test_greed_triggers_one_sell_fraction(self):
        prices = make_prices([100.0] * 252, start="2020-01-02")
        # Stable neutral then sustained greed
        fg_values = [50.0] * 126 + [85.0] * 126
        fg = _fg(fg_values, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly", "greed_threshold": 75, "sell_pct": 0.25},
        )
        sells = [o for o in orders if o.action == Action.SELL_FRACTION]
        assert len(sells) == 1
        assert sells[0].amount == pytest.approx(0.25)

    def test_fear_triggers_one_deploy_reserve(self):
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg_values = [50.0] * 126 + [15.0] * 126
        fg = _fg(fg_values, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        deploys = [o for o in orders if o.action == Action.DEPLOY_RESERVE]
        assert len(deploys) == 1

    def test_greed_fear_alternation_fires_each_side_once_per_episode(self):
        """Greed → neutral → fear → neutral → greed → … fires once per regime."""
        block = (
            [50.0] * 20 + [85.0] * 20 + [50.0] * 20 + [15.0] * 20 + [50.0] * 20
        )  # greed, fear
        prices = make_prices([100.0] * len(block), start="2020-01-02")
        fg = _fg(block, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        sells = [o for o in orders if o.action == Action.SELL_FRACTION]
        deploys = [o for o in orders if o.action == Action.DEPLOY_RESERVE]
        assert len(sells) == 1
        assert len(deploys) == 1

    def test_must_pass_through_neutral_to_re_arm(self):
        """Greed → fear directly (no neutral between) still re-arms the other side."""
        block = [50.0] * 10 + [85.0] * 20 + [15.0] * 20 + [85.0] * 20
        prices = make_prices([100.0] * len(block), start="2020-01-02")
        fg = _fg(block, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        sells = [o for o in orders if o.action == Action.SELL_FRACTION]
        deploys = [o for o in orders if o.action == Action.DEPLOY_RESERVE]
        # greed → sell, fear → deploy, greed again → sell again (entering greed
        # from fear is a fresh greed entry).
        assert len(sells) == 2
        assert len(deploys) == 1

    def test_param_validation(self):
        prices = make_prices([100.0] * 30)
        fg = _fg([50.0] * 30, prices.index)
        ctx = {"prices": prices, "fear_greed": fg}
        with pytest.raises(ValueError, match="fear_threshold"):
            DCAFearGreedRebalance().orders(ctx, 10_000, params={"fear_threshold": 80, "greed_threshold": 20})
        with pytest.raises(ValueError, match="sell_pct"):
            DCAFearGreedRebalance().orders(ctx, 10_000, params={"sell_pct": 1.5})
        with pytest.raises(ValueError, match="not in F&G data"):
            DCAFearGreedRebalance().orders(ctx, 10_000, params={"index_type": "bogus"})
        with pytest.raises(ValueError, match="Unknown cadence"):
            DCAFearGreedRebalance().orders(ctx, 10_000, params={"cadence": "yearly"})

    def test_orders_are_chronological(self):
        block = [50.0] * 50 + [85.0] * 50 + [50.0] * 50 + [15.0] * 50 + [50.0] * 52
        prices = make_prices([100.0] * len(block), start="2020-01-02")
        fg = _fg(block, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        dates = [o.date for o in orders]
        assert dates == sorted(dates)

    def test_total_dca_contributions_equal_total_budget(self):
        """Trim/deploy don't add or remove capital — only DCA does."""
        prices = make_prices([100.0] * 252, start="2020-01-02")
        fg = _fg([50.0] * 252, prices.index)
        orders = DCAFearGreedRebalance().orders(
            {"prices": prices, "fear_greed": fg}, total_budget=10_000,
            params={"cadence": "monthly"},
        )
        deposit_total = sum(
            o.amount for o in orders if o.action == Action.DEPOSIT_AND_BUY
        )
        assert deposit_total == pytest.approx(10_000.0)
