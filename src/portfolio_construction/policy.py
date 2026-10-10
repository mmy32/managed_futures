"""Stateful execution policy: no-trade bands, then hard exposure and risk limits."""

import numpy as np

from src.portfolio_construction.bands import band_positions
from src.portfolio_construction.limits import PortfolioLimits, enforce_limits
from src.risk_model import portfolio_risk
from src.transaction_cost_model import traded_exposure


class BandPolicy:
    def __init__(self, covariance, limits: PortfolioLimits, band):
        self.covariance = covariance
        self.limits = limits
        self.band = band
        self.executed: dict = {}
        self.proposed: dict = {}

    def __call__(self, month, previous, target, cost_model, switched):
        matrix = self.covariance[month]
        proposal = band_positions(previous, target, self.band)
        selected, scale = enforce_limits(
            proposal,
            previous,
            matrix,
            cost_model,
            switched,
            self.limits,
        )
        trades, _ = traded_exposure(selected, previous, switched)
        fee = cost_model.cost(trades)
        forecast = portfolio_risk(selected, matrix)
        gross_after_cost = np.abs(selected).sum() / (1 - fee)
        risk_after_cost = forecast / (1 - fee)
        assert gross_after_cost <= self.limits.gross_cap + 1e-10
        assert risk_after_cost <= self.limits.risk_ceiling + 1e-10
        self.executed[month] = selected.copy()
        self.proposed[month] = proposal.copy()
        proposal_fee = cost_model.cost(traded_exposure(proposal, previous, switched)[0])
        wanted = np.abs(target - previous) > 1e-12
        skipped = wanted & (np.abs(proposal - previous) <= 1e-12)
        return selected, {
            "forecast_vol_annual": forecast,
            "forecast_after_cost": risk_after_cost,
            "gross_after_cost": gross_after_cost,
            "gross_limit_breach": gross_after_cost > self.limits.gross_cap + 1e-10,
            "risk_limit_breach": risk_after_cost > self.limits.risk_ceiling + 1e-10,
            "limit_override": scale < 1 - 1e-10,
            "gross_override": np.abs(proposal).sum()
            > self.limits.gross_cap * (1 - proposal_fee) + 1e-10,
            "risk_override": portfolio_risk(proposal, matrix)
            > self.limits.risk_ceiling * (1 - proposal_fee) + 1e-10,
            "band_skipped_resizes": int(skipped.sum()),
            "net_skipped_resizes": int((skipped & (np.abs(selected - previous) <= 1e-12)).sum()),
            "target_distance_l1": float(np.abs(selected - target).sum()),
            "forecast_tracking_risk": portfolio_risk(selected - target, matrix),
            "drifted_gross_before": float(np.abs(previous).sum()),
        }
