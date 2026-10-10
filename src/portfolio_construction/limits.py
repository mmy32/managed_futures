"""Exposure and risk limits on target and executed positions."""

from dataclasses import dataclass

import numpy as np

from src.risk_model import portfolio_risk
from src.transaction_cost_model import CostModel, traded_exposure


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


def enforce_limits(
    proposed, previous, covariance, cost_model: CostModel, switched, limits: PortfolioLimits
):
    """Largest proportional holding reduction satisfying limits after entry fees."""
    gross = float(np.abs(proposed).sum())
    risk = portfolio_risk(proposed, covariance)
    load = max(gross / limits.gross_cap, risk / limits.risk_ceiling)

    def used_capital(scale):
        fee = cost_model.cost(traded_exposure(scale * proposed, previous, switched)[0])
        return scale * load + fee

    if used_capital(0.0) >= 1:
        raise ValueError("Insufficient capital to close positions")
    if used_capital(1.0) <= 1:
        return proposed.copy(), 1.0
    # Trading costs are piecewise linear; small proportional costs make this monotone.
    if cost_model.cost(np.array([limits.gross_cap])) >= 1:
        raise ValueError("Cost assumption incompatible with proportional limit solver")
    low, high = 0.0, 1.0
    for _ in range(50):
        middle = (low + high) / 2
        if used_capital(middle) <= 1:
            low = middle
        else:
            high = middle
    return proposed * low, low
