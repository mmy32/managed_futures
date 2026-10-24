"""Trailing monthly-return volatility and shrunk-correlation covariance (qps baseline)."""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from src.config import MONTHS_PER_YEAR
from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar


def decay_weights(window: int, half_life: float | None) -> np.ndarray:
    """Weights over a window, oldest first, summing to one; None means equal weights."""
    if half_life is None:
        return np.full(window, 1 / window)
    weights = 0.5 ** (np.arange(window)[::-1] / half_life)
    return weights / weights.sum()


def weighted_covariance(history: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted covariance with the reliability correction; equal weights give ddof=1."""
    centered = history - weights @ history
    return (centered * weights[:, None]).T @ centered / (1 - weights @ weights)


class RollingCovarianceRiskModel:
    """Sample volatility and correlation over the trailing `window` months, lagged.

    Observations are weighted by exponential decay with each of `half_lives` (months) and the
    covariances averaged (fast/slow); None means equal weights, the default.
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
        half_lives: Sequence[float | None] = (None,),
    ):
        if not 0 < correlation_shrinkage <= 1:
            raise ValueError("Shrinkage must be positive and at most one")
        self.window = window
        self.lag = check_lag(lag)
        self.volatility_floor = volatility_floor
        self.correlation_shrinkage = correlation_shrinkage
        self.diagonal = diagonal
        self.weights = [decay_weights(window, half_life) for half_life in half_lives]

    def _covariance(self, history: np.ndarray) -> np.ndarray:
        return np.mean([weighted_covariance(history, w) for w in self.weights], axis=0)

    def _variance(self, history: np.ndarray) -> float:
        return float(
            np.mean([weighted_covariance(history[:, None], w)[0, 0] for w in self.weights])
        )

    def volatility(self, data: MarketData) -> pd.DataFrame:
        check_monthly_calendar(data.returns)
        rolling = data.returns.rolling(self.window, min_periods=self.window)
        variance = rolling.apply(self._variance, raw=True)
        return variance.pow(0.5).mul(np.sqrt(MONTHS_PER_YEAR)).shift(self.lag)

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
                sample_cov = self._covariance(hist.to_numpy())
                vol = np.sqrt(np.diag(sample_cov)) * np.sqrt(MONTHS_PER_YEAR)
                floor_vol = np.maximum(vol, self.volatility_floor)
                if self.diagonal:
                    correlation = np.eye(len(ids))
                else:
                    scale = np.sqrt(np.diag(sample_cov))
                    sample = sample_cov / np.outer(scale, scale)
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
