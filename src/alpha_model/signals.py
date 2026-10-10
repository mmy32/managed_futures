"""Trend signals: one interface, interchangeable definitions of the trailing return."""

from typing import Protocol

import numpy as np
import pandas as pd


class Signal(Protocol):
    """Direction forecast in {-1, 0, +1} per month and market, NaN without a full window.

    forecast() uses returns through month t only; callers apply the information lag.
    """

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame: ...


def _check_lookback(lookback: int) -> int:
    if lookback < 1:
        raise ValueError("Signal lookback must be at least one month")
    return lookback


class SumReturnSignal:
    """Sign of the sum of the trailing monthly returns (qps baseline)."""

    def __init__(self, lookback: int):
        self.lookback = _check_lookback(lookback)

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        window = returns.rolling(self.lookback, min_periods=self.lookback).sum()
        return np.sign(window)


class CompoundedReturnSignal:
    """Sign of the trailing compounded return (Moskowitz-Ooi-Pedersen 2012)."""

    def __init__(self, lookback: int):
        self.lookback = _check_lookback(lookback)

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        if (returns <= -1).any().any():
            raise ValueError("Monthly returns at or below -100% cannot be compounded")
        # sign(prod(1 + r) - 1) == sign(sum(log(1 + r)))
        window = np.log1p(returns).rolling(self.lookback, min_periods=self.lookback).sum()
        return np.sign(window)


class AlwaysLongSignal:
    """+1 wherever a full trailing window exists: the always-long benchmark."""

    def __init__(self, lookback: int):
        self.lookback = _check_lookback(lookback)

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        complete = returns.rolling(self.lookback, min_periods=self.lookback).sum().notna()
        return pd.DataFrame(1.0, index=returns.index, columns=returns.columns).where(complete)


def lagged(forecast: pd.DataFrame, lag: int) -> pd.DataFrame:
    """Value known at month t: the forecast made at the end of month t - lag."""
    if lag < 1:
        raise ValueError("Information lag must be at least one month")
    return forecast.shift(lag)
