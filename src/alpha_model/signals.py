"""Trend signals: one interface, interchangeable definitions of the trailing return."""

from collections.abc import Mapping
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


class SkipMonthSignal:
    """Sign of the compounded return over months t-lookback+1 .. t-skip, leaving out the latest `skip` months."""

    def __init__(self, lookback: int, skip: int = 1):
        self.lookback = _check_lookback(lookback)
        if not 1 <= skip < lookback:
            raise ValueError("Skip must be at least one month and shorter than the lookback")
        self.skip = skip

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        if (returns <= -1).any().any():
            raise ValueError("Monthly returns at or below -100% cannot be compounded")
        window_length = self.lookback - self.skip
        window = (
            np.log1p(returns)
            .shift(self.skip)
            .rolling(window_length, min_periods=window_length)
            .sum()
        )
        return np.sign(window)


class AssetClassSignal:
    """Routes each market to the signal chosen for its asset class; every market must have one."""

    def __init__(self, by_class: Mapping[str, Signal], asset_class: pd.Series):
        self.by_class = dict(by_class)
        self.asset_class = asset_class

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        classes = self.asset_class.reindex(returns.columns)
        unrouted = classes.index[~classes.isin(self.by_class)]
        if len(unrouted):
            raise ValueError(f"No signal for the asset class of: {', '.join(map(str, unrouted))}")
        parts = [
            signal.forecast(returns[classes.index[classes == name]])
            for name, signal in self.by_class.items()
            if (classes == name).any()
        ]
        return pd.concat(parts, axis=1)[returns.columns]


class AlwaysLongSignal:
    """+1 wherever a full trailing window exists: the always-long benchmark."""

    def __init__(self, lookback: int):
        self.lookback = _check_lookback(lookback)

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        complete = returns.rolling(self.lookback, min_periods=self.lookback).sum().notna()
        return pd.DataFrame(1.0, index=returns.index, columns=returns.columns).where(complete)


class AlwaysLongLike:
    """+1 wherever the reference signal has a forecast: the always-long benchmark with the same eligibility."""

    def __init__(self, reference: Signal):
        self.reference = reference

    def forecast(self, returns: pd.DataFrame) -> pd.DataFrame:
        known = self.reference.forecast(returns).notna()
        return pd.DataFrame(1.0, index=returns.index, columns=returns.columns).where(known)


def lagged(forecast: pd.DataFrame, lag: int) -> pd.DataFrame:
    """Value known at month t: the forecast made at the end of month t - lag."""
    if lag < 1:
        raise ValueError("Information lag must be at least one month")
    return forecast.shift(lag)
