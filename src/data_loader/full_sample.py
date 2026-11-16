"""Read declared decimal monthly returns without changing the supplied workbook."""

import re
from datetime import date, datetime
from numbers import Real
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from src.config import FULL_SAMPLE_MONTHLY_RETURNS_PATH


def _headers(cells, path):
    if not cells or cells[0].value not in (None, "Date") or len(cells) < 2:
        raise ValueError(f"{path}: expected a blank/Date header followed by market IDs")
    markets = [cell.value for cell in cells[1:]]
    if any(not isinstance(market, str) or not re.fullmatch(r"[A-Za-z0-9_]+", market)
           for market in markets):
        raise ValueError(f"{path}: market IDs must be nonempty letters, digits or underscores")
    if len(set(markets)) != len(markets):
        raise ValueError(f"{path}: duplicate market IDs")
    return markets


def _month(cell, path):
    value = cell.value
    coordinate = getattr(cell, "coordinate", "date cell")
    if cell.data_type == "f" or not isinstance(value, (datetime, date)):
        raise ValueError(f"{path}: {coordinate} must contain a native Excel date")
    stamp = pd.Timestamp(value)
    if stamp.tz is not None or stamp != stamp.normalize():
        raise ValueError(f"{path}: {coordinate} must be a date without time or timezone")
    month = stamp.to_period("M")
    expected = pd.offsets.BMonthEnd().rollback(month.to_timestamp("M"))
    if stamp != expected:
        raise ValueError(f"{path}: {coordinate} must use the last weekday of its month")
    return month


def _return(cell, path):
    value = cell.value
    if cell.data_type == "f":
        raise ValueError(f"{path}: formulas are not accepted ({cell.coordinate})")
    if value is None:
        return np.nan
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{path}: {cell.coordinate} must contain a numeric decimal return or blank")
    if not np.isfinite(value) or value <= -1:
        raise ValueError(f"{path}: {cell.coordinate} must be finite and greater than -1")
    return float(value)


def _read_sheet(sheet, path):
    rows = iter(sheet.iter_rows())
    markets = _headers(next(rows, ()), path)
    months, observations = [], []
    for cells in rows:
        months.append(_month(cells[0], path))
        observations.append([_return(cell, path) for cell in cells[1:]])
    if not months:
        raise ValueError(f"{path}: no monthly observations")
    index = pd.PeriodIndex(months, freq="M", name="month")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{path}: monthly dates are not sorted ascending")
    if not index.is_unique:
        raise ValueError(f"{path}: duplicate months")
    if not index.equals(pd.period_range(index[0], index[-1], freq="M", name="month")):
        raise ValueError(f"{path}: monthly calendar has missing months")
    result = pd.DataFrame(observations, index=index, columns=markets, dtype=float)
    empty = result.columns[result.isna().all()].tolist()
    if empty:
        raise ValueError(f"{path}: columns with no data: {empty}")
    return result


def load_full_sample_returns(
    path: Path = FULL_SAMPLE_MONTHLY_RETURNS_PATH, *, units: str, sheet_name: str = "Sheet1"
) -> pd.DataFrame:
    """Load one explicit monthly sheet as a complete, ordered monthly PeriodIndex panel.

    ``units='decimal'`` is required: scale is declared by the caller, never
    inferred from magnitudes or cell formatting. Values above +100% are allowed;
    finite simple returns must exceed -100%. Dates must be native Excel dates at
    the final weekday of each month. Blanks remain unknown, including entire
    blank months. Formulas, text returns and duplicate IDs/months are rejected.
    The loader neither fills gaps nor modifies the workbook, selects an evaluation
    period, verifies vendor conventions or certifies an independent holdout.
    """
    if units != "decimal":
        raise ValueError("Declare units='decimal'; other units are unsupported and never inferred")
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"{path}: expected an .xlsx workbook")
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"{path}: missing declared sheet {sheet_name!r}")
        return _read_sheet(workbook[sheet_name], path)
    finally:
        workbook.close()
