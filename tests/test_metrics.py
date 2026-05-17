"""Golden tests for metric calculations."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src import metrics


def _series(values, start="2020-01-02"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


class TestTotalReturn:
    def test_doubles_money(self):
        equity = _series([100, 150, 200])
        deployed = _series([100, 100, 100])
        assert metrics.total_return(equity, deployed) == pytest.approx(1.0)

    def test_loss(self):
        equity = _series([100, 80, 70])
        deployed = _series([100, 100, 100])
        assert metrics.total_return(equity, deployed) == pytest.approx(-0.30)

    def test_dca_uses_total_deployed(self):
        # Deployed grew over time to $200; final equity $250 -> +25%
        equity = _series([100, 200, 250])
        deployed = _series([100, 200, 200])
        assert metrics.total_return(equity, deployed) == pytest.approx(0.25)

    def test_zero_deployed_returns_zero(self):
        equity = _series([0, 0, 0])
        deployed = _series([0, 0, 0])
        assert metrics.total_return(equity, deployed) == 0.0


class TestCagr:
    def test_100_pct_over_exactly_one_year(self):
        # Two anchor dates exactly 365.25 days apart -> CAGR of doubling is exactly 100%.
        idx = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])  # 366 days incl. leap
        equity = pd.Series([100.0, 200.0], index=idx)
        deployed = pd.Series([100.0, 100.0], index=idx)
        # 366 days / 365.25 ≈ 1.00205 years; doubling gives ≈ (2)^(1/1.00205) - 1 ≈ 0.997
        assert metrics.cagr(equity, deployed) == pytest.approx(1.0, abs=0.01)

    def test_flat_is_zero(self):
        equity = _series([100] * 100)
        deployed = _series([100] * 100)
        assert metrics.cagr(equity, deployed) == pytest.approx(0.0, abs=1e-9)

    def test_zero_deployed_returns_zero(self):
        equity = _series([0, 0, 0])
        deployed = _series([0, 0, 0])
        assert metrics.cagr(equity, deployed) == 0.0


class TestMaxDrawdown:
    def test_monotonic_up_is_zero(self):
        equity = _series([100, 110, 120, 130])
        assert metrics.max_drawdown(equity) == pytest.approx(0.0)

    def test_half_loss(self):
        equity = _series([100, 200, 100])  # peak 200 -> 100 = -50%
        assert metrics.max_drawdown(equity) == pytest.approx(-0.5)

    def test_picks_deepest(self):
        equity = _series([100, 90, 100, 50, 80])  # peak 100 -> 50 = -50%, recovers
        assert metrics.max_drawdown(equity) == pytest.approx(-0.5)

    def test_empty(self):
        equity = pd.Series(dtype=float)
        assert metrics.max_drawdown(equity) == 0.0


class TestSummarize:
    def test_keys_and_types(self):
        equity = _series([100, 110, 120])
        deployed = _series([100, 100, 100])
        out = metrics.summarize(equity, deployed, n_buys=1, n_sells=0)
        expected = {
            "final_value", "cash_deployed", "total_return", "cagr",
            "max_drawdown", "n_buys", "n_sells",
        }
        assert set(out) == expected
        assert out["final_value"] == pytest.approx(120.0)
        assert out["cash_deployed"] == pytest.approx(100.0)
        assert out["total_return"] == pytest.approx(0.20)
        assert out["n_buys"] == 1.0
        assert out["n_sells"] == 0.0
