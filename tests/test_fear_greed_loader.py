"""Tests for the CNN F&G fetcher.

The live endpoints are never hit. Tests inject the captured fixtures via the
`fetch` parameter so the suite is deterministic and offline.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import fear_greed

FIXTURES = Path(__file__).parent / "fixtures"
CNN_FIXTURE = FIXTURES / "cnn_fear_greed.json"
WHIT_FIXTURE = FIXTURES / "whit3rabbit_fear_greed.csv"


@pytest.fixture
def cnn_raw() -> dict:
    return json.loads(CNN_FIXTURE.read_text())


@pytest.fixture
def whit_csv() -> str:
    return WHIT_FIXTURE.read_text()


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    """Redirect both per-source caches to a tmp dir so tests never touch user data/."""
    paths = {
        "cnn": tmp_path / "fear_greed_cnn.parquet",
        "whit3rabbit": tmp_path / "fear_greed_whit3rabbit.parquet",
    }
    monkeypatch.setattr(fear_greed, "CACHE_PATH", paths)
    return paths


def _cnn_window(raw: dict) -> tuple[date, date]:
    data = raw["fear_and_greed_historical"]["data"]
    first = pd.Timestamp(data[0]["x"], unit="ms").date()
    last = pd.Timestamp(data[-1]["x"], unit="ms").date()
    return first, last


# ----------------------------------------------------------- parsers ---


class TestParseCnn:
    def test_returns_dataframe_with_fear_greed_column(self, cnn_raw):
        df = fear_greed.parse_cnn(cnn_raw)
        assert isinstance(df, pd.DataFrame)
        assert "fear_greed" in df.columns
        assert len(df) > 0

    def test_index_is_normalized_dates(self, cnn_raw):
        df = fear_greed.parse_cnn(cnn_raw)
        assert (df.index == df.index.normalize()).all()
        assert df.index.tz is None

    def test_scores_are_in_0_100(self, cnn_raw):
        df = fear_greed.parse_cnn(cnn_raw)
        scores = df["fear_greed"].dropna()
        assert (scores >= 0).all()
        assert (scores <= 100).all()

    def test_missing_historical_raises(self):
        with pytest.raises(ValueError, match="fear_and_greed_historical"):
            fear_greed.parse_cnn({})


class TestParseWhit3rabbit:
    def test_returns_dataframe_with_fear_greed_column(self, whit_csv):
        df = fear_greed.parse_whit3rabbit(whit_csv)
        assert "fear_greed" in df.columns

    def test_long_history(self, whit_csv):
        """Whit3rabbit goes back to 2011; we should see >10 years of data."""
        df = fear_greed.parse_whit3rabbit(whit_csv)
        span_days = (df.index.max() - df.index.min()).days
        assert span_days > 10 * 365

    def test_scores_are_in_0_100(self, whit_csv):
        df = fear_greed.parse_whit3rabbit(whit_csv)
        assert (df["fear_greed"] >= 0).all()
        assert (df["fear_greed"] <= 100).all()

    def test_no_component_columns(self, whit_csv):
        """CSV source only has the headline score; strategies asking for components
        should fail when this source is used."""
        df = fear_greed.parse_whit3rabbit(whit_csv)
        assert list(df.columns) == ["fear_greed"]

    def test_unexpected_columns_raises(self):
        with pytest.raises(ValueError, match="Unexpected CSV columns"):
            fear_greed.parse_whit3rabbit("Foo,Bar\n1,2\n")


# ----------------------------------------------------------- loader ---


class TestLoadCnnSource:
    def test_first_load_populates_cache(self, cnn_raw, isolated_cache):
        first, last = _cnn_window(cnn_raw)
        assert not isolated_cache["cnn"].exists()
        df = fear_greed.load_fear_greed(
            start=first, end=last, source="cnn", fetch=lambda: cnn_raw,
        )
        assert isolated_cache["cnn"].exists()
        assert len(df) > 0

    def test_second_load_uses_cache(self, cnn_raw, isolated_cache):
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            return cnn_raw

        first, last = _cnn_window(cnn_raw)
        fear_greed.load_fear_greed(start=first, end=last, source="cnn", fetch=fake_fetch)
        assert calls["n"] == 1
        fear_greed.load_fear_greed(start=first, end=last, source="cnn", fetch=fake_fetch)
        assert calls["n"] == 1

    def test_start_before_cnn_floor_raises(self, cnn_raw, isolated_cache):
        with pytest.raises(ValueError, match="predates available history"):
            fear_greed.load_fear_greed(
                start=date(2019, 1, 1), end=date(2026, 1, 1),
                source="cnn", fetch=lambda: cnn_raw,
            )


class TestLoadWhit3rabbitSource:
    def test_first_load_populates_cache(self, whit_csv, isolated_cache):
        assert not isolated_cache["whit3rabbit"].exists()
        df = fear_greed.load_fear_greed(
            start=date(2011, 1, 3), end=date(2026, 1, 1),
            source="whit3rabbit", fetch=lambda: whit_csv,
        )
        assert isolated_cache["whit3rabbit"].exists()
        assert len(df) > 0

    def test_returns_pre_cnn_history(self, whit_csv, isolated_cache):
        """Where whit3rabbit really earns its keep: data from before 2020-09-18."""
        df = fear_greed.load_fear_greed(
            start=date(2015, 1, 1), end=date(2019, 12, 31),
            source="whit3rabbit", fetch=lambda: whit_csv,
        )
        assert len(df) > 1000  # ~5 years of business days
        assert df.index.min().date() >= date(2015, 1, 1)
        assert df.index.max().date() <= date(2019, 12, 31)

    def test_start_before_2011_raises(self, whit_csv, isolated_cache):
        with pytest.raises(ValueError, match="predates available history"):
            fear_greed.load_fear_greed(
                start=date(2010, 1, 1), end=date(2026, 1, 1),
                source="whit3rabbit", fetch=lambda: whit_csv,
            )


class TestLoadCommon:
    def test_unknown_source_raises(self, isolated_cache):
        with pytest.raises(ValueError, match="Unknown F&G source"):
            fear_greed.load_fear_greed(
                start=date(2023, 1, 1), end=date(2024, 1, 1),
                source="bogus",  # type: ignore[arg-type]
            )

    def test_separate_caches_per_source(self, cnn_raw, whit_csv, isolated_cache):
        """Loading cnn shouldn't write to whit3rabbit cache (and vice-versa)."""
        first, last = _cnn_window(cnn_raw)
        fear_greed.load_fear_greed(
            start=first, end=last, source="cnn", fetch=lambda: cnn_raw,
        )
        assert isolated_cache["cnn"].exists()
        assert not isolated_cache["whit3rabbit"].exists()
        fear_greed.load_fear_greed(
            start=date(2011, 1, 3), end=date(2026, 1, 1),
            source="whit3rabbit", fetch=lambda: whit_csv,
        )
        assert isolated_cache["whit3rabbit"].exists()
