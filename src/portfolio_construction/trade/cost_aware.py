"""Convex, fee-aware tracking of the existing trend targets (optional pc extra)."""

from dataclasses import dataclass
from time import perf_counter

import cvxpy as cp
import numpy as np

from src.config import MONTHS_PER_YEAR
from src.portfolio_construction.scale import PortfolioLimits
from src.portfolio_construction.trade.feasibility import enforce_limits
from src.risk_model import portfolio_risk
from src.transaction_cost_model import LinearBpsCost, traded_exposure
from src.transaction_cost_model.costs import BPS


@dataclass(frozen=True)
class SolverSettings:
    tolerance: float = 1e-8
    feasibility_tolerance: float = 1e-7
    max_iterations: int = 200

    def __post_init__(self):
        if not 0 < self.tolerance <= self.feasibility_tolerance < 1:
            raise ValueError("Require positive solver tolerance <= feasibility tolerance < 1")
        if not isinstance(self.max_iterations, int) or self.max_iterations < 1:
            raise ValueError("Solver iteration limit must be a positive integer")


def _problem(size, gamma, limits):
    """One DPP problem per active dimension; all monthly data are parameters."""
    z, trade = cp.Variable(size, nonneg=True), cp.Variable(size, nonneg=True)
    params = dict(
        factor=cp.Parameter((size, size)), desired=cp.Parameter(size),
        prior=cp.Parameter(size), rate=cp.Parameter(nonneg=True),
        exit_fee=cp.Parameter(nonneg=True),
    )
    risk_vector = params["factor"] @ z
    fee = params["rate"] * cp.sum(trade) + params["exit_fee"]
    objective = gamma / (2 * MONTHS_PER_YEAR) * cp.sum_squares(
        risk_vector - params["desired"]
    ) + fee
    constraints = [
        trade >= z - params["prior"], trade >= params["prior"] - z,
        cp.sum(z) <= limits.gross_cap * (1 - fee),
        cp.norm(risk_vector) <= limits.risk_ceiling * (1 - fee),
    ]
    problem = cp.Problem(cp.Minimize(BPS * objective), constraints)
    if not problem.is_dcp(dpp=True):
        raise ValueError("Tracking problem must be convex and DPP compliant")
    return problem, z, params


class CostAwarePolicy:
    """Minimize monthly tracking variance plus linear trading costs, using no realized returns.

    Covariance is annualized. Zero targets force liquidation; other positions retain
    the target sign. Shared factor_cache must belong to this covariance forecast set.
    """

    def __init__(self, covariance, limits: PortfolioLimits, gamma,
                 settings=None, factor_cache=None):
        if not np.isfinite(gamma) or gamma <= 0:
            raise ValueError("gamma must be finite and positive")
        if not all(np.isfinite(x) and x > 0 for x in (limits.gross_cap, limits.risk_ceiling)):
            raise ValueError("Portfolio limits must be finite and positive")
        self.covariance, self.limits, self.gamma = covariance, limits, float(gamma)
        self.settings = settings or SolverSettings()
        self.factor_cache = {} if factor_cache is None else factor_cache
        self.problems: dict = {}
        self.executed: dict = {}
        self.proposed: dict = {}
        self.solve_count = 0
        self.failure = None

    def _inputs(self, month, previous, target, cost_model, switched, roll_charge):
        if type(cost_model) is not LinearBpsCost or roll_charge is not None:
            raise ValueError("CostAwarePolicy supports ordinary LinearBpsCost only; no roll charges")
        if not np.isfinite(cost_model.rate) or cost_model.rate < 0:
            raise ValueError("Nonfinite or negative cost rate")
        previous, target = np.asarray(previous, float), np.asarray(target, float)
        matrix, switched = np.asarray(self.covariance[month]), np.asarray(switched, bool)
        n = len(target)
        if (previous.shape != (n,) or target.shape != (n,) or switched.shape != (n,)
                or matrix.shape != (n, n)):
            raise ValueError("Policy inputs must have aligned dimensions")
        if not all(np.isfinite(x).all() for x in (previous, target, matrix)):
            raise ValueError("Nonfinite policy input")
        if not np.allclose(matrix, matrix.T, rtol=0, atol=self.settings.tolerance):
            raise ValueError("Covariance must be symmetric")
        if cost_model.cost(np.abs(previous)) >= 1:
            raise ValueError("Insufficient capital to close positions")
        if cost_model.rate * self.limits.gross_cap >= 1:
            raise ValueError("Cost rate incompatible with portfolio limit guard")
        return previous, target, matrix, switched

    def _factor(self, month, ids, matrix):
        key = (month, tuple(ids))
        if key not in self.factor_cache:
            try:
                factor = np.linalg.cholesky(matrix[np.ix_(ids, ids)]).T
            except np.linalg.LinAlgError as error:
                raise ValueError("Active covariance must be positive definite") from error
            self.factor_cache[key] = factor
        return self.factor_cache[key]

    def _solve(self, month, previous, target, matrix, switched, cost_model):
        ids = np.flatnonzero(target)
        result = np.zeros_like(target)
        if not len(ids):
            return result, dict(solver_status="flat", solver_iterations=0, solver_seconds=0.0)
        signs = np.sign(target[ids])
        factor = self._factor(month, ids, matrix)
        if len(ids) not in self.problems:
            self.problems[len(ids)] = _problem(len(ids), self.gamma, self.limits)
        problem, variable, params = self.problems[len(ids)]
        params["factor"].value = factor * signs
        params["desired"].value = factor @ target[ids]
        params["prior"].value = np.where(
            switched[ids], -np.abs(previous[ids]), signs * previous[ids]
        )
        params["rate"].value = cost_model.rate
        params["exit_fee"].value = cost_model.cost(np.abs(previous[target == 0]))
        try:
            self._optimize(problem)
        except ValueError as error:
            self.failure = dict(
                month=str(month), gamma=self.gamma, solver_status=problem.status,
                previous=previous.tolist(), target=target.tolist(),
                covariance=matrix.tolist(), switched=switched.tolist(), cost_bps=cost_model.rate * BPS,
            )
            raise ValueError(f"{month}: {error}") from error
        result[ids] = signs * np.asarray(variable.value).reshape(-1)
        return result, dict(
            solver_status=problem.status, solver_iterations=problem.solver_stats.num_iters,
            solver_seconds=problem.solver_stats.solve_time,
        )

    def _optimize(self, problem):
        try:
            problem.solve(
                solver="CLARABEL", warm_start=True, enforce_dpp=True,
                max_iter=self.settings.max_iterations,
                tol_gap_abs=self.settings.tolerance, tol_gap_rel=self.settings.tolerance,
                tol_feas=self.settings.tolerance,
            )
        except cp.error.SolverError as error:
            raise ValueError(f"Portfolio optimization failed: {error}") from error
        self.solve_count += 1
        if problem.status != cp.OPTIMAL:
            raise ValueError(f"Portfolio optimization failed: {problem.status}")

    def _validate(self, proposal, previous, target, matrix, cost_model, switched):
        if not np.isfinite(proposal).all():
            raise ValueError("Nonfinite optimized holdings")
        fee = cost_model.cost(traded_exposure(proposal, previous, switched)[0])
        residual = max(
            0.0, float(np.max(-proposal * np.sign(target), initial=0)),
            float(np.max(np.abs(proposal[target == 0]), initial=0)),
            float(np.abs(proposal).sum() - self.limits.gross_cap * (1 - fee)),
            float(portfolio_risk(proposal, matrix) - self.limits.risk_ceiling * (1 - fee)),
        )
        if fee >= 1 or residual > self.settings.feasibility_tolerance:
            raise ValueError(f"Optimized holdings fail independent feasibility check: {residual}")
        # Remove numerical sign noise, then use the shared exact fee-aware limit guard.
        cleaned = np.sign(target) * np.maximum(0, proposal * np.sign(target))
        selected, scale = enforce_limits(
            cleaned, previous, matrix, cost_model, switched, self.limits
        )
        adjustment = float(np.max(np.abs(selected - proposal), initial=0))
        if adjustment > self.settings.feasibility_tolerance:
            raise ValueError(f"Material post-solver adjustment: {adjustment}")
        return selected, scale, residual, adjustment

    def __call__(self, month, previous, target, cost_model, switched, roll_charge=None):
        started = perf_counter()
        previous, target, matrix, switched = self._inputs(
            month, previous, target, cost_model, switched, roll_charge
        )
        proposal, solver = self._solve(month, previous, target, matrix, switched, cost_model)
        selected, scale, residual, adjustment = self._validate(
            proposal, previous, target, matrix, cost_model, switched
        )
        fee = cost_model.cost(traded_exposure(selected, previous, switched)[0])
        risk = portfolio_risk(selected, matrix)
        tracking = portfolio_risk(selected - target, matrix)
        self.proposed[month], self.executed[month] = proposal.copy(), selected.copy()
        return selected, dict(
            **solver, gamma=self.gamma, policy_seconds=perf_counter() - started,
            solver_feasibility_residual=residual, solver_guard_adjustment=adjustment,
            solver_problem_count=len(self.problems), limit_override=scale < 1,
            forecast_vol_annual=risk, forecast_after_cost=risk / (1 - fee),
            gross_after_cost=np.abs(selected).sum() / (1 - fee),
            gross_limit_breach=np.abs(selected).sum() / (1 - fee) > self.limits.gross_cap + 1e-10,
            risk_limit_breach=risk / (1 - fee) > self.limits.risk_ceiling + 1e-10,
            forecast_tracking_risk=tracking, target_distance_l1=np.abs(selected - target).sum(),
            drifted_gross_before=np.abs(previous).sum(),
            tracking_objective=self.gamma / (2 * MONTHS_PER_YEAR) * tracking**2 + fee,
        )
