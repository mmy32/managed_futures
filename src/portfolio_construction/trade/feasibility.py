"""Executed limits: the largest proportional cut that keeps the limits after entry fees."""

import numpy as np

from src.portfolio_construction.scale import PortfolioLimits
from src.risk_model import portfolio_risk
from src.transaction_cost_model import CostModel, traded_exposure


def enforce_limits(
    proposed, previous, covariance, cost_model: CostModel, switched, limits: PortfolioLimits
):
    """Largest proportional holding reduction satisfying limits after entry fees (bisection)."""
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
