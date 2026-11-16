"""Calibration rescale: scale a risk model's covariance by a past-only ratio (the C1 fallback)."""

import numpy as np
import pandas as pd

from src.config import MONTHS_PER_YEAR
from src.risk_model.base import RiskModel

FORECAST_VOL_EPSILON = 1e-12  # forecast volatility at or below this counts as no forecast


def standardized_returns(ledger: pd.DataFrame) -> pd.Series:
    """Gross return over the forecast monthly volatility; its std is the calibration."""
    forecast = ledger.forecast_vol_annual
    valid = forecast > FORECAST_VOL_EPSILON
    return ledger.loc[valid, "gross_return"] / (forecast[valid] / np.sqrt(MONTHS_PER_YEAR))


def trailing_scale(standardized: pd.Series, window: int, minimum: int, lag: int = 1) -> pd.Series:
    """Standard deviation of past standardized returns, used from the month after `lag`.

    `standardized` is return / forecast monthly volatility. The value at month t uses months
    through t - lag only; it is 1.0 until `minimum` observations are available.
    """
    if any(type(value) is not int or value < 1 for value in (window, minimum, lag)):
        raise ValueError("Calibration window, minimum and lag must be positive integers")
    if minimum < 2 or minimum > window:
        raise ValueError("Calibration requires 2 <= minimum <= window")
    if not isinstance(standardized.index, pd.PeriodIndex) or standardized.index.freqstr != "M":
        raise ValueError("Calibration requires a monthly PeriodIndex")
    if not standardized.index.is_unique or not standardized.index.is_monotonic_increasing:
        raise ValueError("Calibration months must be ordered and unique")
    if standardized.empty:
        return standardized.copy()
    # Zero-risk months are omitted by standardized_returns. Restore their calendar
    # slots before rolling/shifting so 60 months and lag two keep their stated units.
    calendar = pd.period_range(standardized.index[0], standardized.index[-1], freq="M")
    monthly = standardized.reindex(calendar)
    ratio = monthly.rolling(window, min_periods=minimum).std(ddof=1).shift(lag)
    return ratio.fillna(1.0)


class ScaledRiskModel:
    """Multiply the covariance forecast of `model` by scale[month]**2, leaving sizing unchanged.

    Volatility (used for position sizing) passes through; only the covariance used for the risk
    ceiling is rescaled, so the ceiling binds as if it were `ceiling / scale`.
    """

    def __init__(self, model: RiskModel, scale: pd.Series):
        if (scale <= 0).any() or not np.isfinite(scale).all():
            raise ValueError("Scale must be positive and finite")
        self.model = model
        self.scale = scale

    def volatility(self, data):
        return self.model.volatility(data)

    def covariances(self, data, eligible):
        covariance, details = self.model.covariances(data, eligible)
        scaled = {
            month: matrix * self.scale.loc[month] ** 2 for month, matrix in covariance.items()
        }
        return scaled, details
