"""Shared fixtures for backtest tests.

All prices are synthetic so tests are deterministic, fast, and never need network.
"""

from __future__ import annotations

import pandas as pd
import pytest


def make_prices(values: list[float], start: str = "2020-01-02") -> pd.DataFrame:
    """Build an OHLCV-ish DataFrame from a series of close prices on business days.

    Open=High=Low=Close=adj_close so execution math is unambiguous.
    """
    idx = pd.bdate_range(start, periods=len(values))
    s = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": s, "high": s, "low": s, "close": s, "adj_close": s, "volume": 1_000},
        index=idx,
    )


@pytest.fixture
def flat_prices() -> pd.DataFrame:
    """100 business days, price = $100 throughout."""
    return make_prices([100.0] * 100)


@pytest.fixture
def linear_prices() -> pd.DataFrame:
    """100 business days, price ramps linearly from $100 to $200."""
    return make_prices([100.0 + i * (100.0 / 99) for i in range(100)])


@pytest.fixture
def v_shape_prices() -> pd.DataFrame:
    """V-shaped: $100 → $50 over 50 days, back to $100 over 50 days. Useful for max-DD."""
    down = [100.0 - i * (50.0 / 49) for i in range(50)]
    up = [50.0 + i * (50.0 / 49) for i in range(50)]
    return make_prices(down + up)
