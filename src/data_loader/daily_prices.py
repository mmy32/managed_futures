"""Load daily futures prices from the per-market CSVs."""

from pathlib import Path

import numpy as np
import pandas as pd

from src.config import DAILY_BAR_FIELDS, FUTURES_UNDERLYING_DIR, PRICE_COLUMN


def _load_close(path: Path) -> pd.Series:
    data = pd.read_csv(path, index_col=0, parse_dates=True)
    if PRICE_COLUMN not in data.columns:
        raise ValueError(f"{path}: missing {PRICE_COLUMN} column")
    close = data[PRICE_COLUMN]
    if not close.index.is_monotonic_increasing:
        raise ValueError(f"{path}: dates are not sorted ascending")
    if not close.index.is_unique:
        raise ValueError(f"{path}: duplicate dates")
    if close.isna().any():
        raise ValueError(f"{path}: missing {PRICE_COLUMN} values")
    if (close <= 0).any():
        raise ValueError(f"{path}: non-positive {PRICE_COLUMN} values")
    return close.rename(path.stem)


def load_daily_prices(directory: Path = FUTURES_UNDERLYING_DIR) -> pd.DataFrame:
    """Return daily closing prices, one column per market ID (the CSV file stem).

    Dates are the union across markets, so a market is NaN outside its own history.
    Raises ValueError if the directory has no CSVs or any file fails validation.
    """
    paths = sorted(directory.glob("*.csv"))
    if not paths:
        raise ValueError(f"{directory}: no CSV files found")
    return pd.concat([_load_close(path) for path in paths], axis=1)


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
