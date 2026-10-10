"""Risk model interface: annualized volatility for sizing, covariance for limits."""

from typing import Protocol

import numpy as np
import pandas as pd

from src.models import MarketData


class RiskModel(Protocol):
    def volatility(self, data: MarketData) -> pd.DataFrame:
        """Annualized volatility known at each month (information lag applied), PeriodIndex."""
        ...

    def covariances(
        self, data: MarketData, eligible: pd.DataFrame
    ) -> tuple[dict[pd.Period, np.ndarray], dict[pd.Period, dict]]:
        """Annualized covariance per month over eligible markets (zeros elsewhere), plus details."""
        ...


def check_monthly_calendar(returns: pd.DataFrame) -> None:
    if not isinstance(returns.index, pd.PeriodIndex) or not returns.index.equals(
        pd.period_range(returns.index.min(), returns.index.max(), freq="M")
    ):
        raise ValueError("Risk inputs must have a unique, ordered, complete monthly calendar")


def check_lag(lag: int) -> int:
    if not isinstance(lag, int) or lag < 1:
        raise ValueError("Risk forecasts require an integer information lag of at least one month")
    return lag
