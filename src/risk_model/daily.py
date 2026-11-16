"""Covariance from daily returns over the same trailing months as the monthly baseline."""

import numpy as np
import pandas as pd

from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar

TRADING_DAYS_PER_YEAR = 252
def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Return close ratios only where adjacent observation-grid prices are known.

    Missing quotes are not proof of a holiday or a zero return. Leave both the
    missing observation and the first ratio after it unknown; the latter spans
    an unverified interval. A verified session-calendar adapter can supply its
    own observations before this boundary, without changing the raw prices.
    """
    if not isinstance(prices.index, pd.DatetimeIndex) or not (
        prices.index.is_unique and prices.index.is_monotonic_increasing
    ):
        raise ValueError("Daily prices require ordered, unique dates")
    if not prices.columns.is_unique:
        raise ValueError("Daily prices require unique market IDs")
    values = prices.to_numpy(dtype=float)
    if np.isinf(values).any() or (values[np.isfinite(values)] <= 0).any():
        raise ValueError("Observed daily prices must be positive and finite")
    return prices / prices.shift(1) - 1


def shrunk_covariance(
    vol: np.ndarray, correlation: np.ndarray, floor: float, shrinkage: float
) -> np.ndarray:
    """Annual covariance from volatilities and a correlation matrix, as the monthly baseline."""
    shrunk = (1 - shrinkage) * correlation + shrinkage * np.eye(len(vol))
    floored = np.maximum(vol, floor)
    matrix = shrunk * np.outer(floored, floored)
    if not (np.isfinite(matrix).all() and np.allclose(matrix, matrix.T)):
        raise ValueError("Forecast covariance is not finite and symmetric")
    if float(np.min(np.linalg.eigvalsh(matrix))) <= 0:
        raise ValueError("Forecast covariance is not positive definite on eligible assets")
    return matrix


def window_dates(month: pd.Period, lag: int, window: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last calendar day of the `window` months ending `lag` months before `month`."""
    end = month - lag
    return (end - window + 1).start_time, end.end_time.normalize()


def complete_monthly_window(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    """True where a market has `window` consecutive monthly returns: the baseline's universe."""
    return returns.notna().astype(int).rolling(window, min_periods=window).sum() == window


class DailyCovarianceRiskModel:
    """Trailing-window covariance estimated from daily returns, lagged like the monthly model.

    Volatility is the daily standard deviation over the window times sqrt(trading days per
    year). Correlation uses returns summed over blocks of `block_days` (1 = daily, 5 = weekly
    blocks), which reduces the bias from markets closing at different times. Correlations are
    shrunk toward the identity and volatilities floored exactly as in the monthly model.
    A market is eligible only where the monthly baseline would be, and where its daily window
    has no missing day, so the market universe matches the baseline's.
    """

    def __init__(
        self,
        daily: pd.DataFrame,
        window: int,
        lag: int,
        volatility_floor: float,
        correlation_shrinkage: float,
        block_days: int = 1,
    ):
        if not 0 < correlation_shrinkage <= 1:
            raise ValueError("Shrinkage must be positive and at most one")
        if block_days < 1:
            raise ValueError("block_days must be at least one")
        self.daily = daily
        self.window = window
        self.lag = check_lag(lag)
        self.volatility_floor = volatility_floor
        self.correlation_shrinkage = correlation_shrinkage
        self.block_days = block_days

    def _window(self, month: pd.Period, markets: list[str]) -> pd.DataFrame:
        start, end = window_dates(month, self.lag, self.window)
        return self.daily.loc[start:end, markets]

    def volatility(self, data: MarketData) -> pd.DataFrame:
        check_monthly_calendar(data.returns)
        eligible = complete_monthly_window(data.returns, self.window).shift(
            self.lag, fill_value=False
        )
        eligible.loc[:, ~eligible.columns.isin(self.daily.columns)] = False
        vol = pd.DataFrame(np.nan, index=data.returns.index, columns=data.returns.columns)
        for month in data.returns.index[eligible.any(axis=1)]:
            markets = list(eligible.columns[eligible.loc[month]])
            history = self._window(month, markets)
            usable = history.columns[history.notna().all()]
            vol.loc[month, usable] = history[usable].std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        return vol

    def _blocks(self, history: np.ndarray) -> np.ndarray:
        if self.block_days == 1:
            return history
        count = len(history) // self.block_days
        trimmed = np.log1p(history[len(history) - count * self.block_days :])
        return trimmed.reshape(count, self.block_days, -1).sum(axis=1)

    def covariances(self, data, eligible):
        covariance, details = {}, {}
        size = data.returns.shape[1]
        for month in eligible.index:
            ids = np.flatnonzero(eligible.loc[month].to_numpy())
            matrix = np.zeros((size, size))
            eigenvalue = np.nan
            if len(ids):
                markets = list(data.returns.columns[ids])
                history = self._window(month, markets)
                if history.isna().any().any():
                    raise ValueError("Incomplete daily estimation window")
                daily = history.to_numpy()
                vol = daily.std(axis=0, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
                correlation = np.corrcoef(self._blocks(daily), rowvar=False)
                matrix[np.ix_(ids, ids)] = shrunk_covariance(
                    vol,
                    np.atleast_2d(correlation),
                    self.volatility_floor,
                    self.correlation_shrinkage,
                )
                eigenvalue = float(np.linalg.eigvalsh(matrix[np.ix_(ids, ids)]).min())
            covariance[month] = matrix
            details[month] = {
                "information_through": month - self.lag,
                "estimation_start": month - self.lag - self.window + 1,
                "min_eigenvalue": eigenvalue,
            }
        return covariance, details
