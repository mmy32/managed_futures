"""Exponentially weighted daily volatility (Moskowitz-Ooi-Pedersen 2012, Eq. 1)."""

import numpy as np
import pandas as pd

from src.config import (
    EWMA_CENTER_OF_MASS_DAYS,
    EWMA_MIN_OBSERVATIONS,
    EWMA_TRADING_DAYS_PER_YEAR,
)
from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar


def ewma_daily_volatility(
    prices: pd.Series,
    center_of_mass: float = EWMA_CENTER_OF_MASS_DAYS,
    trading_days: int = EWMA_TRADING_DAYS_PER_YEAR,
    min_observations: int = EWMA_MIN_OBSERVATIONS,
) -> pd.Series:
    """Annualized EWMA volatility of daily returns, known at each date's close.

    Variance is the exponentially weighted mean of squared deviations from the
    exponentially weighted mean return, with weights (1 - d) * d**i, d = com / (1 + com).
    """
    closes = prices.dropna()
    returns = closes.pct_change().dropna()
    mean = returns.ewm(com=center_of_mass, adjust=False, min_periods=min_observations).mean()
    mean_square = (
        (returns**2).ewm(com=center_of_mass, adjust=False, min_periods=min_observations).mean()
    )
    variance = (mean_square - mean**2).clip(lower=0.0)
    return np.sqrt(trading_days * variance)


class EwmaVolatilityRiskModel:
    """Month-end EWMA volatility from daily prices, lagged; covariance is diagonal.

    The paper sizes each market on its own volatility and applies no portfolio-level
    limit, so no cross-market correlation is estimated.
    """

    def __init__(
        self,
        lag: int,
        center_of_mass: float = EWMA_CENTER_OF_MASS_DAYS,
        trading_days: int = EWMA_TRADING_DAYS_PER_YEAR,
        min_observations: int = EWMA_MIN_OBSERVATIONS,
    ):
        self.lag = check_lag(lag)
        self.center_of_mass = center_of_mass
        self.trading_days = trading_days
        self.min_observations = min_observations

    def volatility(self, data: MarketData) -> pd.DataFrame:
        check_monthly_calendar(data.returns)
        if data.prices is None:
            raise ValueError("EWMA volatility requires daily prices")
        months = data.returns.index
        monthly = {}
        for market in data.returns.columns:
            if market not in data.prices:
                raise ValueError(f"No daily prices for {market}")
            daily = ewma_daily_volatility(
                data.prices[market], self.center_of_mass, self.trading_days, self.min_observations
            )
            # Last daily estimate of each month; markets without data in a month stay NaN.
            monthly[market] = daily.groupby(daily.index.to_period("M")).last().reindex(months)
        return pd.DataFrame(monthly, index=months).shift(self.lag)

    def covariances(self, data, eligible):
        vol = self.volatility(data).reindex(eligible.index)
        covariance, details = {}, {}
        for month in eligible.index:
            active = eligible.loc[month].to_numpy()
            matrix = np.zeros((len(active), len(active)))
            variances = np.where(active, vol.loc[month].to_numpy() ** 2, 0.0)
            matrix[np.diag_indices_from(matrix)] = variances
            covariance[month] = matrix
            details[month] = {
                "information_through": month - self.lag,
                "estimation_start": pd.NaT,
                "min_eigenvalue": float(variances[active].min()) if active.any() else np.nan,
            }
        return covariance, details
