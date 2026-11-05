"""Exposure and risk limits on the target book."""

from dataclasses import dataclass

import numpy as np

from src.risk_model import portfolio_risk


@dataclass(frozen=True)
class PortfolioLimits:
    gross_cap: float  # maximum gross exposure, in units of NAV
    risk_ceiling: float  # maximum forecast annual portfolio volatility


def bounded_target(weights, covariance, limits: PortfolioLimits):
    gross, risk = np.abs(weights).sum(), portfolio_risk(weights, covariance)
    scale = min(
        1.0,
        limits.gross_cap / gross if gross else 1.0,
        limits.risk_ceiling / risk if risk else 1.0,
    )
    return weights * scale
