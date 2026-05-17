"""Tests for the HTML report renderer (trade log + page assembly)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.engine import Trade
from src.report import _trade_log_html


def _trade(date: str, side: str, shares: float, price: float, notional: float, commission: float) -> Trade:
    return Trade(
        date=pd.Timestamp(date),
        side=side,
        shares=shares,
        price=price,
        notional=notional,
        commission=commission,
    )


class TestTradeLogHtml:
    def test_no_trades_message(self):
        html = _trade_log_html([], "buy_hold")
        assert "No trades executed" in html

    def test_renders_each_trade_with_running_shares(self):
        trades = [
            _trade("2020-01-02", "buy", 10.0, 100.0, 1000.0, 0.5),
            _trade("2020-02-03", "buy", 5.0, 110.0, 550.0, 0.275),
            _trade("2020-05-01", "sell", 15.0, 120.0, 1800.0, 0.9),
        ]
        html = _trade_log_html(trades, "rsi")
        # Header row
        assert "Trade log" in html
        assert "3 trades — 2 buys, 1 sells" in html
        # Each date appears
        assert "2020-01-02" in html
        assert "2020-02-03" in html
        assert "2020-05-01" in html
        # Side classes for color
        assert "side buy" in html
        assert "side sell" in html
        # Running shares column should reach 15 after both buys, then 0 after the sell.
        # Render shares as "15.0000" (4dp) so we can search for it.
        assert "15.0000" in html
        assert "0.0000" in html

    def test_escapes_html_safely(self):
        """Money values include $ and , — make sure they don't break the layout."""
        trades = [_trade("2020-01-02", "buy", 12.3456, 1234.5, 15234.57, 7.62)]
        html = _trade_log_html(trades, "buy_hold")
        assert "$1,234.50" in html
        assert "$15,234.57" in html
