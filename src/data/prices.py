"""Daily OHLCV price loader with Parquet cache."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path("data/prices")
COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}.parquet"


def _fetch(ticker: str, start: date, end: date) -> pd.DataFrame:
    raw = yf.download(
        ticker,
        start=start.isoformat(),
        end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        raise ValueError(f"No data returned for {ticker} {start}..{end}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    raw.index = pd.DatetimeIndex(raw.index).normalize()
    raw.index.name = "date"
    return raw[COLUMNS]


def load_prices(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Return daily OHLCV for `ticker` between `start` and `end` (inclusive).

    Caches per-ticker Parquet under data/prices/. On cache hit, fetches only
    the missing tail and merges.
    """
    ticker = ticker.upper()
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    path = _cache_path(ticker)

    if path.exists():
        cached = pd.read_parquet(path)
        cached.index = pd.DatetimeIndex(cached.index).normalize()
        cached_max = cached.index.max()
        cached_min = cached.index.min()

        need_earlier = start_ts < cached_min
        need_later = end_ts > cached_max

        if need_earlier or need_later:
            fetch_start = min(start, cached_min.date())
            fetch_end = max(end, cached_max.date())
            fresh = _fetch(ticker, fetch_start, fetch_end)
            merged = pd.concat([cached, fresh])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(path)
            df = merged
        else:
            df = cached
    else:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df = _fetch(ticker, start, end)
        df.to_parquet(path)

    df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
    if df.empty:
        raise ValueError(
            f"No price rows for {ticker} between {start} and {end} after filtering cache"
        )
    return df
