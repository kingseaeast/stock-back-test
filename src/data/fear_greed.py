"""CNN Fear & Greed index loader.

Two data sources are supported:

  - "cnn" (default): the unofficial JSON endpoint CNN's own site uses
    (https://production.dataviz.cnn.io/index/fearandgreed/graphdata).
    Appending /YYYY-MM-DD returns data from that date forward; the API
    itself only has data back to 2020-09-18 (anything earlier returns
    HTTP 500). Includes the headline score plus several component
    sub-indices (market_momentum_sp500, market_volatility_vix, ...).

  - "whit3rabbit": a community-maintained CSV mirror at
    https://github.com/whit3rabbit/fear-greed-data — refreshed weekly,
    headline score only, but reaches back to 2011-01-03 by stitching
    older archives. Use this when you need long backtest windows. The
    repo has no license, so treat the data as research-only and don't
    redistribute.

Tests inject `fetch` to avoid network calls and `cache_path` (looked up
at call time) to avoid polluting the user's data/ dir.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path
from typing import Callable, Literal

import pandas as pd
import requests

# Per-source cache files so different sources don't clobber each other.
CACHE_PATH = {
    "cnn": Path("data/fear_greed_cnn.parquet"),
    "whit3rabbit": Path("data/fear_greed_whit3rabbit.parquet"),
}

# Earliest date each source can serve.
EARLIEST = {
    "cnn": date(2020, 9, 18),         # verified: anything earlier returns HTTP 500
    "whit3rabbit": date(2011, 1, 3),  # first row of the canonical CSV
}

Source = Literal["cnn", "whit3rabbit"]

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
WHIT3RABBIT_URL = (
    "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv"
)

# Browser-like headers — CNN's edge blocks plain `requests` UA.
CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://edition.cnn.com",
    "Referer": "https://edition.cnn.com/",
}

# Top-level component sub-indices in the CNN payload, each with its own historical series.
COMPONENT_KEYS = (
    "market_momentum_sp500",
    "stock_price_strength",
    "stock_price_breadth",
    "put_call_options",
    "market_volatility_vix",
    "safe_haven_demand",
    "junk_bond_demand",
)


# ---------------------------------------------------------------- fetchers ---


def _fetch_cnn(start: date) -> dict:
    """Hit CNN's endpoint with a start-date suffix (clamped to the API floor)."""
    floor = EARLIEST["cnn"]
    effective_start = max(start, floor)
    url = f"{CNN_URL}/{effective_start.isoformat()}"
    response = requests.get(url, headers=CNN_HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()


def _fetch_whit3rabbit() -> str:
    response = requests.get(WHIT3RABBIT_URL, timeout=30)
    response.raise_for_status()
    return response.text


# ----------------------------------------------------------------- parsers ---


def parse_cnn(raw: dict) -> pd.DataFrame:
    """Convert the CNN JSON payload into a daily DataFrame.

    Columns: `fear_greed` plus one per available component sub-index.
    """
    main_hist = raw.get("fear_and_greed_historical", {}).get("data", [])
    if not main_hist:
        raise ValueError("CNN response missing fear_and_greed_historical.data")
    frames = [_series_from_cnn_entries(main_hist, "fear_greed")]
    for key in COMPONENT_KEYS:
        comp = raw.get(key, {}).get("data") or raw.get(key, {}).get("historical")
        if not comp:
            continue
        frames.append(_series_from_cnn_entries(comp, key))
    df = pd.concat(frames, axis=1).sort_index()
    df.index.name = "date"
    return df


def parse_whit3rabbit(csv_text: str) -> pd.DataFrame:
    """Convert the whit3rabbit CSV into the same shape as `parse_cnn`.

    The CSV only has the headline score, so the returned frame only has
    the `fear_greed` column. Strategies that ask for component sub-indices
    will fail loudly when this source is used.
    """
    raw = pd.read_csv(StringIO(csv_text))
    if list(raw.columns)[:2] != ["Date", "Fear Greed"]:
        raise ValueError(
            f"Unexpected CSV columns: {list(raw.columns)}; expected Date,Fear Greed,..."
        )
    idx = pd.DatetimeIndex(pd.to_datetime(raw["Date"])).tz_localize(None).normalize()
    out = pd.DataFrame({"fear_greed": raw["Fear Greed"].astype(float).values}, index=idx)
    out.index.name = "date"
    return out.sort_index()


def _series_from_cnn_entries(entries: list[dict], column: str) -> pd.DataFrame:
    rows = [
        (pd.Timestamp(entry["x"], unit="ms").normalize(), float(entry["y"]))
        for entry in entries
    ]
    out = pd.DataFrame(rows, columns=["date", column]).set_index("date")
    out.index = out.index.tz_localize(None)
    return out


# ----------------------------------------------------------- public loader ---


def load_fear_greed(
    start: date,
    end: date,
    source: Source = "cnn",
    fetch: Callable | None = None,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """Return F&G data for [start, end] from the given source.

    Reads from the per-source Parquet cache when possible; refreshes from the
    live source when the cache is missing or its tail is older than `end`.
    Raises if `start` predates the source's available history.
    """
    if source not in EARLIEST:
        raise ValueError(f"Unknown F&G source {source!r}. Use one of {sorted(EARLIEST)}")
    if start < EARLIEST[source]:
        raise ValueError(
            f"F&G source {source!r} only has data from {EARLIEST[source].isoformat()}; "
            f"requested start {start.isoformat()} predates available history."
        )

    if cache_path is None:
        cache_path = CACHE_PATH[source]
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()

    cached: pd.DataFrame | None = None
    if cache_path.exists():
        cached = pd.read_parquet(cache_path)
        cached.index = pd.DatetimeIndex(cached.index).normalize()

    need_refresh = cached is None or cached.index.max() < end_ts
    if need_refresh:
        df = _refresh(source, start, fetch)
        if cached is not None:
            df = pd.concat([cached, df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path)
    else:
        df = cached

    df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
    if df.empty:
        raise ValueError(f"No F&G rows between {start} and {end} after filtering.")
    return df


def _refresh(source: Source, start: date, fetch: Callable | None) -> pd.DataFrame:
    if source == "cnn":
        raw = fetch() if fetch is not None else _fetch_cnn(start)
        return parse_cnn(raw)
    if source == "whit3rabbit":
        text = fetch() if fetch is not None else _fetch_whit3rabbit()
        return parse_whit3rabbit(text)
    raise ValueError(f"Unknown source {source!r}")
