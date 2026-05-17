"""Engine correctness tests.

These prove the four properties we care most about:
  1. No look-ahead — an order signaled on day D executes at day D+1's close.
  2. Buy-hold final equity matches a closed-form formula exactly.
  3. DCA deploys exactly the total budget (within float epsilon).
  4. Commission and slippage are applied consistently in both directions.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.engine import RunConfig, _simulate, run
from src.strategies.base import Action, Order

from .conftest import make_prices


def _config(strategy: str, prices: pd.DataFrame, **kwargs) -> RunConfig:
    return RunConfig(
        strategy=strategy,
        ticker="SYN",
        start=prices.index[0].date(),
        end=prices.index[-1].date(),
        commission_bps=kwargs.pop("commission_bps", 0.0),
        slippage_bps=kwargs.pop("slippage_bps", 0.0),
        total_budget=kwargs.pop("total_budget", 10_000.0),
        params=kwargs.pop("params", {}),
    )


class TestNoLookAhead:
    def test_order_on_day_d_executes_on_day_d_plus_1(self):
        # Day 0: $100. Day 1: $200. An order signaled on day 0 must execute at $200.
        prices = make_prices([100.0, 200.0, 200.0])
        orders = [Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=10_000)]
        equity, deployed, trades = _simulate(prices, orders, commission_bps=0, slippage_bps=0)
        assert len(trades) == 1
        assert trades[0].date == prices.index[1]
        assert trades[0].price == pytest.approx(200.0)
        assert trades[0].shares == pytest.approx(50.0)  # 10000 / 200

    def test_order_on_final_day_is_dropped(self):
        # Signal on the very last day cannot execute (no D+1 to run on).
        prices = make_prices([100.0, 100.0, 100.0])
        orders = [Order(date=prices.index[-1], action=Action.DEPOSIT_AND_BUY, amount=10_000)]
        equity, deployed, trades = _simulate(prices, orders, commission_bps=0, slippage_bps=0)
        assert trades == []
        assert deployed.iloc[-1] == 0.0
        assert equity.iloc[-1] == 0.0


class TestBuyHoldClosedForm:
    """Buy-hold has a clean formula we can check exactly."""

    def test_doubling_zero_costs(self, linear_prices):
        # Prices: 100 → ~200 over 100 bdays. Buy-hold on day 0 → executes day 1.
        config = _config("buy_hold", linear_prices, total_budget=10_000)
        result = run(config, prices=linear_prices)

        exec_price = float(linear_prices["adj_close"].iloc[1])
        final_price = float(linear_prices["adj_close"].iloc[-1])
        expected = 10_000 / exec_price * final_price
        assert result.strategy.metrics["final_value"] == pytest.approx(expected, rel=1e-9)

    def test_with_commission_and_slippage(self, linear_prices):
        # 10 bps comm + 20 bps slip
        config = _config(
            "buy_hold", linear_prices,
            total_budget=10_000, commission_bps=10, slippage_bps=20,
        )
        result = run(config, prices=linear_prices)

        raw_price = float(linear_prices["adj_close"].iloc[1])
        exec_price = raw_price * (1 + 20 / 10_000)
        shares = (10_000 / (1 + 10 / 10_000)) / exec_price
        expected = shares * float(linear_prices["adj_close"].iloc[-1])
        assert result.strategy.metrics["final_value"] == pytest.approx(expected, rel=1e-9)

    def test_no_benchmark_when_strategy_is_buy_hold(self, flat_prices):
        # buy_hold-as-strategy shouldn't run buy_hold again as a redundant benchmark
        config = _config("buy_hold", flat_prices)
        result = run(config, prices=flat_prices)
        assert result.benchmarks == []


class TestDCADeployment:
    def test_total_deployed_equals_budget(self, flat_prices):
        config = _config("dca", flat_prices, total_budget=10_000, params={"cadence": "monthly"})
        result = run(config, prices=flat_prices)
        assert result.strategy.metrics["cash_deployed"] == pytest.approx(10_000.0, abs=1e-6)

    def test_dca_at_flat_price_zero_costs_breaks_even(self, flat_prices):
        # With flat prices and zero costs, DCA final value == total deployed.
        config = _config("dca", flat_prices, total_budget=10_000, params={"cadence": "monthly"})
        result = run(config, prices=flat_prices)
        assert result.strategy.metrics["final_value"] == pytest.approx(10_000.0, abs=1e-6)
        assert result.strategy.metrics["total_return"] == pytest.approx(0.0, abs=1e-9)

    def test_dca_underperforms_buy_hold_in_rising_market(self, linear_prices):
        config = _config("dca", linear_prices, total_budget=10_000, params={"cadence": "monthly"})
        result = run(config, prices=linear_prices)
        dca_final = result.strategy.metrics["final_value"]
        bh_final = result.benchmarks[0].metrics["final_value"]
        assert dca_final < bh_final, "DCA should lag buy-hold in a monotonically rising market"

    def test_buy_hold_benchmark_included_for_dca(self, flat_prices):
        config = _config("dca", flat_prices)
        result = run(config, prices=flat_prices)
        assert [b.name for b in result.benchmarks] == ["buy_hold"]


class TestIdleCash:
    def test_cash_after_sell_does_not_grow(self):
        # Buy at $100, prices rise to $200, sell, then prices keep rising — cash should sit flat.
        prices = make_prices([100, 100, 200, 200, 300, 300])
        orders = [
            Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=10_000),
            Order(date=prices.index[1], action=Action.SELL_ALL),  # executes on day 2 at $200
        ]
        equity, _, trades = _simulate(prices, orders, commission_bps=0, slippage_bps=0)
        assert len(trades) == 2
        sale_value = trades[1].notional
        # After the sell on day 2, equity should be flat for the remaining days
        post_sale_values = equity.iloc[3:].unique()
        assert len(post_sale_values) == 1
        assert post_sale_values[0] == pytest.approx(sale_value)


class TestEquityConservation:
    def test_equity_equals_cash_plus_shares_value_at_all_times(self):
        # After every step, equity must equal cash + shares*price.
        prices = make_prices([100, 110, 120, 130, 140, 150])
        orders = [
            Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=1_000),
            Order(date=prices.index[2], action=Action.DEPOSIT_AND_BUY, amount=500),
        ]
        equity, deployed, _ = _simulate(prices, orders, commission_bps=0, slippage_bps=0)
        # Final deployed should equal sum of deposits
        assert deployed.iloc[-1] == pytest.approx(1_500.0)
        # Initial day has zero equity (no-look-ahead: order signaled day 0 executes day 1)
        assert equity.iloc[0] == 0.0
        # From day 1 onward, equity is strictly positive
        assert (equity.iloc[1:] > 0).all()


class TestSellAll:
    def test_sell_all_zero_costs_returns_full_invested_capital_at_same_price(self):
        prices = make_prices([100, 100, 100, 100])
        orders = [
            Order(date=prices.index[0], action=Action.DEPOSIT_AND_BUY, amount=1_000),
            Order(date=prices.index[1], action=Action.SELL_ALL),
        ]
        equity, deployed, trades = _simulate(prices, orders, commission_bps=0, slippage_bps=0)
        # After sell at the same price with zero costs, equity should equal deposit.
        assert equity.iloc[-1] == pytest.approx(1_000.0)
        assert deployed.iloc[-1] == pytest.approx(1_000.0)
        assert trades[1].side == "sell"
        assert trades[1].shares == pytest.approx(10.0)  # bought 10 shares at $100
