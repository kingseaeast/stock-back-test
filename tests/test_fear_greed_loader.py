"""Tests for the CNN F&G fetcher.

The live endpoint is never hit. Tests inject the captured JSON fixture via the
`fetch` parameter so the suite is deterministic and offline.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import fear_greed

FIXTURE = Path(__file__).parent / "fixtures" / "cnn_fear_greed.json"


@pytest.fixture
def raw_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch) -> Path:
    """Use a temp cache path so tests never read or write the user's data/."""
    cache = tmp_path / "fear_greed.parquet"
    monkeypatch.setattr(fear_greed, "CACHE_PATH", cache)
    return cache


class TestParse:
    def test_returns_dataframe_with_fear_greed_column(self, raw_fixture):
        df = fear_greed.parse(raw_fixture)
        assert isinstance(df, pd.DataFrame)
        assert "fear_greed" in df.columns
        assert len(df) > 0

    def test_index_is_normalized_dates(self, raw_fixture):
        df = fear_greed.parse(raw_fixture)
        # All index entries should be at midnight (normalized)
        assert (df.index == df.index.normalize()).all()
        assert df.index.tz is None

    def test_scores_are_in_0_100(self, raw_fixture):
        df = fear_greed.parse(raw_fixture)
        scores = df["fear_greed"].dropna()
        assert (scores >= 0).all()
        assert (scores <= 100).all()

    def test_missing_historical_raises(self):
        with pytest.raises(ValueError, match="fear_and_greed_historical"):
            fear_greed.parse({})


def _fixture_window(raw: dict) -> tuple[date, date]:
    data = raw["fear_and_greed_historical"]["data"]
    first = pd.Timestamp(data[0]["x"], unit="ms").date()
    last = pd.Timestamp(data[-1]["x"], unit="ms").date()
    return first, last


class TestLoad:
    def test_first_load_populates_cache(self, raw_fixture, isolated_cache):
        first, last = _fixture_window(raw_fixture)
        assert not isolated_cache.exists()
        df = fear_greed.load_fear_greed(
            start=first, end=last, fetch=lambda: raw_fixture,
        )
        assert isolated_cache.exists()
        assert len(df) > 0

    def test_second_load_uses_cache(self, raw_fixture, isolated_cache):
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return raw_fixture

        first, last = _fixture_window(raw_fixture)
        fear_greed.load_fear_greed(start=first, end=last, fetch=fake_fetch)
        assert calls["n"] == 1

        # Second call asking for data within the cached range should NOT refetch
        fear_greed.load_fear_greed(start=first, end=last, fetch=fake_fetch)
        assert calls["n"] == 1, "Should have served the second call from cache"

    def test_start_before_available_raises(self, raw_fixture, isolated_cache):
        with pytest.raises(ValueError, match="predates available history"):
            fear_greed.load_fear_greed(
                start=date(2010, 1, 1),
                end=date(2030, 1, 1),
                fetch=lambda: raw_fixture,
            )

    def test_empty_window_raises(self, raw_fixture, isolated_cache):
        # Both start and end after available data -> empty after filtering
        last_date = pd.Timestamp(
            raw_fixture["fear_and_greed_historical"]["data"][-1]["x"], unit="ms",
        ).date()
        with pytest.raises(ValueError, match="No F&G rows"):
            fear_greed.load_fear_greed(
                start=date(last_date.year + 5, 1, 1),
                end=date(last_date.year + 5, 12, 31),
                fetch=lambda: raw_fixture,
            )
