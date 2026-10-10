"""Inputs shared by every risk model."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MarketData:
    """Monthly returns, asset classes and optional daily closes for one market universe.

    returns: monthly price returns, complete monthly PeriodIndex, one column per market.
    meta: AssetClass by market ID.
    prices: daily closes, DatetimeIndex, one column per market; needed by daily-data models.
    """

    returns: pd.DataFrame
    meta: pd.DataFrame
    prices: pd.DataFrame | None = None
