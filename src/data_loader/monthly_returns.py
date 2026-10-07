"""Load the monthly returns panel."""

from pathlib import Path

import pandas as pd

from src.config import MONTHLY_DATE_FORMAT, MONTHLY_RETURNS_PATH


def load_monthly_returns(path: Path = MONTHLY_RETURNS_PATH) -> pd.DataFrame:
    """Return monthly returns indexed by date, with one column per market ID.

    Raises ValueError on unparseable, unsorted or duplicate dates, non-numeric
    cells, or columns with no data.
    """
    raw = pd.read_csv(path, index_col=0)
    index = pd.DatetimeIndex(pd.to_datetime(raw.index, format=MONTHLY_DATE_FORMAT))
    if not index.is_monotonic_increasing:
        raise ValueError(f"{path}: dates are not sorted ascending")
    if not index.is_unique:
        raise ValueError(f"{path}: duplicate dates")
    if raw.columns.duplicated().any():
        raise ValueError(f"{path}: duplicate market IDs")
    returns = raw.apply(pd.to_numeric)
    returns.index = index
    empty = returns.columns[returns.isna().all()].tolist()
    if empty:
        raise ValueError(f"{path}: columns with no data: {empty}")
    return returns
