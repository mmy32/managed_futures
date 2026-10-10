"""Trailing monthly-return volatility and shrunk-correlation covariance (qps baseline)."""

import numpy as np
import pandas as pd

from src.config import MONTHS_PER_YEAR
from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar


class RollingCovarianceRiskModel:
    """Sample volatility and correlation over the trailing `window` months, lagged.

    Correlations are shrunk toward the identity by `correlation_shrinkage`;
    `diagonal=True` ignores correlations. Volatilities are floored at `volatility_floor`.
    """

    def __init__(
        self,
        window: int,
        lag: int,
        volatility_floor: float,
        correlation_shrinkage: float,
        diagonal: bool = False,
    ):
        if not 0 < correlation_shrinkage <= 1:
            raise ValueError("Shrinkage must be positive and at most one")
        self.window = window
        self.lag = check_lag(lag)
        self.volatility_floor = volatility_floor
        self.correlation_shrinkage = correlation_shrinkage
        self.diagonal = diagonal

    def volatility(self, data: MarketData) -> pd.DataFrame:
        check_monthly_calendar(data.returns)
        rolling = data.returns.rolling(self.window, min_periods=self.window)
        return rolling.std(ddof=1).mul(np.sqrt(MONTHS_PER_YEAR)).shift(self.lag)

    def covariances(self, data, eligible):
        returns = data.returns
        check_monthly_calendar(returns)
        covariance, details = {}, {}
        for month in eligible.index:
            active = eligible.loc[month].to_numpy()
            ids = np.flatnonzero(active)
            matrix = np.zeros((returns.shape[1], returns.shape[1]))
            # Lag=1: endpoint t-1 is the latest input, even when t's return is missing.
            end = returns.index.get_loc(month) - self.lag + 1
            hist = returns.iloc[end - self.window : end, ids]
            if len(ids):
                if len(hist) != self.window or hist.isna().any().any():
                    raise ValueError("Incomplete common estimation window")
                vol = hist.std(ddof=1).to_numpy() * np.sqrt(MONTHS_PER_YEAR)
                floor_vol = np.maximum(vol, self.volatility_floor)
                if self.diagonal:
                    correlation = np.eye(len(ids))
                else:
                    sample = hist.corr().to_numpy()
                    shrinkage = self.correlation_shrinkage
                    correlation = (1 - shrinkage) * sample + shrinkage * np.eye(len(ids))
                small = correlation * np.outer(floor_vol, floor_vol)
                assert np.isfinite(small).all() and np.allclose(small, small.T)
                eigenvalue = float(np.linalg.eigvalsh(small).min())
                if eigenvalue <= 0:
                    raise ValueError(
                        "Forecast covariance is not positive definite on eligible assets"
                    )
                matrix[np.ix_(ids, ids)] = small
            else:
                eigenvalue = np.nan
            covariance[month] = matrix
            details[month] = {
                "information_through": month - self.lag,
                "estimation_start": month - self.lag - self.window + 1,
                "min_eigenvalue": eigenvalue,
            }
        return covariance, details
