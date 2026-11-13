"""Load daily futures prices from the per-market CSVs."""

import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import DAILY_BAR_FIELDS, FUTURES_UNDERLYING_DIR, PRICE_COLUMN


def _load_close(path: Path, iso_dates: bool = False) -> pd.Series:
    if iso_dates:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            header = next(csv.reader(stream), [])
        if header.count(PRICE_COLUMN) != 1:
            raise ValueError(f"{path}: expected exactly one {PRICE_COLUMN} column")
    data = pd.read_csv(path, index_col=0, parse_dates=not iso_dates)
    if iso_dates:
        dates = data.index.map(str)
        if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) for date in dates):
            raise ValueError(f"{path}: dates must use YYYY-MM-DD")
        data.index = pd.to_datetime(dates, format="%Y-%m-%d", errors="raise")
    if PRICE_COLUMN not in data.columns:
        raise ValueError(f"{path}: missing {PRICE_COLUMN} column")
    close = pd.to_numeric(data[PRICE_COLUMN], errors="raise")
    if close.empty:
        raise ValueError(f"{path}: no {PRICE_COLUMN} observations")
    if not close.index.is_monotonic_increasing:
        raise ValueError(f"{path}: dates are not sorted ascending")
    if not close.index.is_unique:
        raise ValueError(f"{path}: duplicate dates")
    if not np.isfinite(close.to_numpy()).all():
        raise ValueError(f"{path}: non-finite {PRICE_COLUMN} values")
    if (close <= 0).any():
        raise ValueError(f"{path}: non-positive {PRICE_COLUMN} values")
    return close.rename(path.stem)


def load_daily_prices(
    directory: Path = FUTURES_UNDERLYING_DIR, markets: list[str] | None = None, *,
    iso_dates: bool = False,
) -> pd.DataFrame:
    """Return daily closing prices, one column per market ID (the CSV file stem).

    Dates are the union across markets, so a market is NaN outside its own history.
    When markets is supplied, load exactly those predeclared file stems in order.
    `iso_dates` requires unambiguous YYYY-MM-DD dates and a single Close column.
    Raises ValueError if a required CSV is missing or any file fails validation.
    """
    paths = sorted(directory.glob("*.csv")) if markets is None else [
        directory / f"{market}.csv" for market in markets
    ]
    if not paths:
        raise ValueError(f"{directory}: no CSV files found")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing declared daily-price files: {missing}")
    return pd.concat([_load_close(path, iso_dates=iso_dates) for path in paths], axis=1)


def load_daily_bars(directory: Path = FUTURES_UNDERLYING_DIR) -> dict[str, pd.DataFrame]:
    """Return the full daily bars (open, high, low, close, volume, open interest) per market ID.

    Raises ValueError on unexpected columns, unparseable, unsorted or duplicate dates, or
    non-finite cells. Price plausibility is left to the caller (the audit reports it).
    """
    paths = sorted(directory.glob("*.csv"))
    if not paths:
        raise ValueError(f"{directory}: no CSV files found")
    bars = {}
    for path in paths:
        data = pd.read_csv(path, index_col=0)
        if list(data.columns) != DAILY_BAR_FIELDS:
            raise ValueError(f"{path}: columns {list(data.columns)} != {DAILY_BAR_FIELDS}")
        data.index = pd.to_datetime(data.index, errors="raise")
        if not (data.index.is_unique and data.index.is_monotonic_increasing):
            raise ValueError(f"{path}: dates are not unique and sorted ascending")
        data = data.apply(pd.to_numeric, errors="raise")
        if not np.isfinite(data.to_numpy()).all():
            raise ValueError(f"{path}: missing or non-finite values")
        bars[path.stem] = data
    return bars
