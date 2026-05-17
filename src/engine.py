"""Backtest engine: turn strategy orders into an equity curve.

Execution rule (no look-ahead): an Order dated D is executed at the **next
trading day** using that day's adjusted close. If D is the very last trading
day in the window, the order is dropped (we can't execute "next day").

Idle cash earns 0%. Commission and slippage are bps applied to notional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from . import metrics
from . import strategies
from .strategies.base import Action, Order


@dataclass(frozen=True)
class RunConfig:
    strategy: str
    ticker: str
    start: date
    end: date
    params: dict[str, Any] = field(default_factory=dict)
    total_budget: float = 10_000.0
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    # Strategy-agnostic options for data loaders (e.g. {"fg_source": "whit3rabbit"}).
    # Kept separate from `params` because data-source choice is a backend concern,
    # not a strategy parameter.
    data_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    date: pd.Timestamp
    side: str          # "buy" | "sell"
    shares: float
    price: float       # execution price after slippage
    notional: float    # cash that moved
    commission: float


@dataclass(frozen=True)
class StrategyRun:
    name: str
    equity: pd.Series                    # portfolio value per day (cash + shares*price)
    cash_deployed: pd.Series             # cumulative dollars added to portfolio
    trades: list[Trade]
    metrics: dict[str, float]


@dataclass(frozen=True)
class Result:
    config: RunConfig
    strategy: StrategyRun
    benchmarks: list[StrategyRun]
    run_id: str


def _simulate(
    prices: pd.DataFrame,
    orders: list[Order],
    commission_bps: float,
    slippage_bps: float,
) -> tuple[pd.Series, pd.Series, list[Trade]]:
    """Walk through trading days, applying orders dated *before* each day at that
    day's adjusted close. Return (equity, cash_deployed, trades).
    """
    close = prices["adj_close"].astype(float)
    trading_days = list(close.index)
    day_index = {d: i for i, d in enumerate(trading_days)}

    # Group orders by execution day (the trading day strictly after their signal date)
    by_exec_day: dict[pd.Timestamp, list[Order]] = {}
    for order in orders:
        signal_idx = day_index.get(order.date)
        if signal_idx is None:
            # Signal date isn't a trading day in window; snap to first trading day >= signal
            # If everything is before window, drop. If after, drop.
            future = [d for d in trading_days if d >= order.date]
            if not future:
                continue
            signal_idx = day_index[future[0]] - 1  # so exec = future[0]
        exec_idx = signal_idx + 1
        if exec_idx >= len(trading_days):
            continue
        by_exec_day.setdefault(trading_days[exec_idx], []).append(order)

    cash = 0.0
    shares = 0.0
    cash_deployed_total = 0.0
    equity_series = []
    deployed_series = []
    trades: list[Trade] = []

    slip = slippage_bps / 10_000.0
    comm = commission_bps / 10_000.0

    def buy_all_available_cash(day: pd.Timestamp, price: float) -> None:
        nonlocal cash, shares
        if cash <= 0:
            return
        exec_price = price * (1 + slip)
        # Solve: bought_shares*exec_price * (1 + comm) == cash
        spend_on_shares = cash / (1 + comm)
        bought_shares = spend_on_shares / exec_price
        notional = bought_shares * exec_price
        commission = notional * comm
        shares += bought_shares
        cash -= notional + commission
        trades.append(Trade(day, "buy", bought_shares, exec_price, notional, commission))

    def sell_all_shares(day: pd.Timestamp, price: float) -> None:
        nonlocal cash, shares
        if shares <= 0:
            return
        exec_price = price * (1 - slip)
        notional = shares * exec_price
        commission = notional * comm
        cash += notional - commission
        trades.append(Trade(day, "sell", shares, exec_price, notional, commission))
        shares = 0.0

    for day in trading_days:
        price = float(close.loc[day])
        for order in by_exec_day.get(day, []):
            if order.action == Action.DEPOSIT_AND_BUY:
                cash += order.amount
                cash_deployed_total += order.amount
                buy_all_available_cash(day, price)
            elif order.action == Action.BUY_ALL_CASH:
                buy_all_available_cash(day, price)
            elif order.action == Action.SELL_ALL:
                sell_all_shares(day, price)

        equity_series.append(cash + shares * price)
        deployed_series.append(cash_deployed_total)

    equity = pd.Series(equity_series, index=close.index, name="equity")
    deployed = pd.Series(deployed_series, index=close.index, name="cash_deployed")
    return equity, deployed, trades


def _run_one(
    name: str,
    strategy_cls: type,
    context: dict[str, pd.DataFrame],
    config: RunConfig,
    params: dict[str, Any],
) -> StrategyRun:
    strategy = strategy_cls()
    orders = strategy.orders(context, config.total_budget, params)
    prices = context["prices"]
    equity, deployed, trades = _simulate(prices, orders, config.commission_bps, config.slippage_bps)
    n_buys = sum(1 for t in trades if t.side == "buy")
    n_sells = sum(1 for t in trades if t.side == "sell")
    return StrategyRun(
        name=name,
        equity=equity,
        cash_deployed=deployed,
        trades=trades,
        metrics=metrics.summarize(equity, deployed, n_buys, n_sells),
    )


def _build_context(
    requirements: frozenset[str],
    config: RunConfig,
    prices: pd.DataFrame | None,
    extras: dict[str, pd.DataFrame] | None,
) -> dict[str, pd.DataFrame]:
    """Load every data source the strategy declared it needs.

    Sources beyond `prices` are aligned to the prices' trading-day index and
    forward-filled (so a sentiment reading taken on Saturday applies to Monday).
    """
    extras = extras or {}
    if prices is None:
        from .data.prices import load_prices
        prices = load_prices(config.ticker, config.start, config.end)

    context: dict[str, pd.DataFrame] = {"prices": prices}

    if "fear_greed" in requirements:
        if "fear_greed" in extras:
            fg = extras["fear_greed"]
        else:
            from .data.fear_greed import load_fear_greed
            fg_source = config.data_options.get("fg_source", "cnn")
            fg = load_fear_greed(config.start, config.end, source=fg_source)
        # Align to trading days. F&G is daily including weekends/holidays; forward-fill.
        fg_aligned = fg.reindex(prices.index.union(fg.index)).sort_index().ffill().reindex(prices.index)
        context["fear_greed"] = fg_aligned

    unknown = requirements - set(context)
    if unknown:
        raise ValueError(f"Unknown data requirements: {sorted(unknown)}")
    return context


def run(
    config: RunConfig,
    prices: pd.DataFrame | None = None,
    extras: dict[str, pd.DataFrame] | None = None,
) -> Result:
    """Execute the strategy in `config` plus benchmarks (buy_hold and DCA-monthly).

    `prices` and `extras` allow tests to inject data without hitting the network.
    """
    strategy_cls = strategies.get(config.strategy)
    context = _build_context(strategy_cls.data_requirements, config, prices, extras)
    strategy_run = _run_one(
        config.strategy, strategy_cls, context, config, config.params
    )

    # Benchmarks always operate on prices only.
    price_context = {"prices": context["prices"]}
    benchmarks: list[StrategyRun] = []
    if config.strategy != "buy_hold":
        benchmarks.append(
            _run_one("buy_hold", strategies.get("buy_hold"), price_context, config, params={})
        )
    if config.strategy != "dca":
        benchmarks.append(
            _run_one(
                "dca_monthly", strategies.get("dca"), price_context, config,
                params={"cadence": "monthly"},
            )
        )

    run_id = _build_run_id(config)
    return Result(config=config, strategy=strategy_run, benchmarks=benchmarks, run_id=run_id)


def _build_run_id(config: RunConfig) -> str:
    # Millisecond precision — earlier "seconds-only" format collided when two runs
    # of the same strategy/ticker fired in the same second (e.g. seeding scripts).
    now = pd.Timestamp.now(tz="UTC")
    ts = now.strftime("%Y%m%d-%H%M%S") + f"{int(now.microsecond / 1000):03d}"
    return f"{ts}_{config.strategy}_{config.ticker.upper()}"
