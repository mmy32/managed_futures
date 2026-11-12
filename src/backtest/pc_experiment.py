"""Past-only policy selection and matched-risk diagnostics for the PC experiment."""

import numpy as np
import pandas as pd

from src.backtest.engine import simulate
from src.backtest.performance import performance
from src.backtest.sample_diagnostics import risk_diagnostics
from src.portfolio_construction import BandPolicy, PortfolioLimits
from src.portfolio_construction.trade.cost_aware import CostAwarePolicy, SolverSettings
from src.risk_model import portfolio_risk
from src.transaction_cost_model import LinearBpsCost


def validate_specification(spec):
    for field in ["cost_bps", "reference_band", "confidence"]:
        if not np.isfinite(spec[field]):
            raise ValueError(f"Nonfinite {field}")
    if spec["cost_bps"] < 0 or not 0 <= spec["reference_band"] < 1:
        raise ValueError("Invalid trading cost or band")
    grid = spec["gamma_grid"]
    if not grid or len(set(grid)) != len(grid) or any(not np.isfinite(g) or g <= 0 for g in grid):
        raise ValueError("gamma grid must contain distinct positive finite values")
    for field in ["selection_minimum_months", "selection_validation_months",
                  "selection_block_months", "bootstrap_draws", "comparison_family_size",
                  "primary_information_lag_months", "sensitivity_information_lag_months"]:
        if not isinstance(spec[field], int) or spec[field] < 1:
            raise ValueError(f"{field} must be a positive integer")
    if spec["selection_validation_months"] > spec["selection_minimum_months"]:
        raise ValueError("Selection warmup must cover its validation window")
    if spec["selection_validation_months"] % spec["selection_block_months"]:
        raise ValueError("Validation window must contain complete selection blocks")
    if spec["comparison_family_size"] < len(grid) + 2 or not 0 < spec["confidence"] < 1:
        raise ValueError("Invalid bootstrap family or confidence")
    if not spec["bootstrap_blocks"] or any(
        not isinstance(b, int) or b < 1 for b in spec["bootstrap_blocks"]
    ):
        raise ValueError("Invalid bootstrap blocks")
    SolverSettings(**spec["solver"])


def policies(covariance, limits, spec):
    """Independent portfolio state, shared immutable covariance factor cache."""
    factors: dict = {}
    result = {"band10": BandPolicy(covariance, limits, spec["reference_band"]),
              "full": BandPolicy(covariance, limits, 0)}
    for gamma in spec["gamma_grid"]:
        result[f"gamma{gamma:g}"] = CostAwarePolicy(
            covariance, limits, gamma, SolverSettings(**spec["solver"]), factors
        )
    return result


def select_policy(ledgers, spec, end):
    """Select at position end using only observations strictly before end.

    Fixed-policy shadow paths supply chronological validation observations. Their
    artificial terminal liquidation is removed from selection scores, not reports.
    """
    baseline = ledgers["band10"]
    if not 0 <= end <= len(baseline):
        raise ValueError("Selection endpoint outside available history")
    if end < spec["selection_minimum_months"]:
        return "band10", []
    start = end - spec["selection_validation_months"]
    reference = baseline.iloc[start:end]
    scores = []
    for gamma in spec["gamma_grid"]:
        name = f"gamma{gamma:g}"
        if not ledgers[name].index.equals(baseline.index):
            raise ValueError("Selection requires matched calendars")
        candidate = ledgers[name].iloc[start:end]
        delta = (candidate.net_return + candidate.liquidation_cost
                 - reference.net_return - reference.liquidation_cost)
        if not np.isfinite(delta).all() or not np.isfinite(candidate.rebalance_turnover).all():
            raise ValueError("Nonfinite selection observations")
        scores.append(dict(
            policy=name, gamma=gamma, information_through=str(reference.index[-1]),
            validation_start=str(reference.index[0]), validation_months=len(reference),
            net_difference_ann=float(delta.mean() * 12),
            turnover_ann=float(candidate.rebalance_turnover.mean() * 12),
        ))
    best = min(scores, key=lambda s: (-s["net_difference_ann"], s["turnover_ann"], s["gamma"]))
    return (best["policy"] if best["net_difference_ann"] > 0 else "band10"), scores


def selection_schedule(ledgers, spec):
    index = ledgers["band10"].index
    if not index.equals(pd.period_range(index.min(), index.max(), freq="M")):
        raise ValueError("Selection requires a complete monthly calendar")
    schedule = pd.Series("band10", index=index, name="policy")
    records = []
    for position in range(spec["selection_minimum_months"], len(index), spec["selection_block_months"]):
        selected, scores = select_policy(ledgers, spec, position)
        schedule.iloc[position:position + spec["selection_block_months"]] = selected
        records.extend(dict(decision_month=str(index[position]), selected=selected, **s) for s in scores)
    return schedule, pd.DataFrame(records)


class ScheduledPolicy:
    """Switch the decision rule, retaining the engine's actual portfolio state."""

    def __init__(self, policy_set, schedule):
        self.policy_set, self.schedule = policy_set, schedule

    def __call__(self, month, previous, target, cost_model, switched, roll_charge=None):
        name = self.schedule.loc[month]
        weights, details = self.policy_set[name](
            month, previous, target, cost_model, switched, roll_charge=roll_charge
        )
        return weights, dict(details, selected_policy=name)


def run_case(sample, targets, covariance, source, known, policy, spec):
    details: dict = {}
    ledger, gross = simulate(
        sample, targets, LinearBpsCost(spec["cost_bps"]), source,
        position_policy=policy, source_known_at=known, instrument_details=details,
    )
    np.testing.assert_allclose(ledger.turnover * spec["cost_bps"] / 10000, ledger.cost, atol=1e-12)
    np.testing.assert_allclose(ledger.gross_return - ledger.cost, ledger.net_return, atol=1e-12)
    if ledger.gross_limit_breach.any() or ledger.risk_limit_breach.any():
        raise ValueError("Executed portfolio breaches limits")
    if (details["exposure"] * targets).lt(-1e-12).any().any():
        raise ValueError("Executed exposure contradicts signal")
    if details["exposure"].where(targets.eq(0), 0).ne(0).any().any():
        raise ValueError("Zero target must execute flat")
    return ledger, gross, details


def case_metrics(name, ledger):
    result = dict(run=name, **performance(ledger), **risk_diagnostics(ledger)[1])
    result.update(
        gross_mean_ann=float(ledger.gross_return.mean() * 12),
        tracking_risk_mean=float(ledger.forecast_tracking_risk.mean()),
        max_gross_after_cost=float(ledger.gross_after_cost.max()),
        max_forecast_after_cost=float(ledger.forecast_after_cost.max()),
        limit_override_months=int(ledger.limit_override.sum()),
    )
    if "solver_seconds" in ledger:
        seconds = ledger.solver_seconds.dropna()
        result.update(
            solver_seconds_total=float(seconds.sum()),
            solver_seconds_p50=float(seconds.median()),
            solver_seconds_p95=float(seconds.quantile(0.95)),
            solver_iterations_max=float(ledger.solver_iterations.max()),
            solver_residual_max=float(ledger.solver_feasibility_residual.max()),
            solver_guard_adjustment_max=float(ledger.solver_guard_adjustment.max()),
        )
    return result


def paired_results(ledgers, score_start):
    baseline = ledgers["band10"].loc[score_start:]
    differences, rows = {}, []
    for name, full_ledger in ledgers.items():
        if name == "band10":
            continue
        ledger = full_ledger.loc[score_start:]
        delta = ledger.net_return - baseline.net_return
        gross = float((ledger.gross_return - baseline.gross_return).mean() * 12)
        saving = float((baseline.cost - ledger.cost).mean() * 12)
        np.testing.assert_allclose(delta.mean() * 12, gross + saving, atol=1e-12)
        differences[name] = delta
        rows.append(dict(run=name, months=len(delta), gross_difference_ann=gross,
                         cost_savings_ann=saving, net_difference_ann=float(delta.mean() * 12)))
    return pd.DataFrame(differences), pd.DataFrame(rows)


class CommonRiskPolicy:
    """Replay supplied ex ante directions at a common after-entry-fee risk ceiling."""

    def __init__(self, covariance, gross_cap, ceilings):
        self.covariance, self.gross_cap, self.ceilings = covariance, gross_cap, ceilings

    def __call__(self, month, previous, target, cost_model, switched, roll_charge=None):
        # Zero risk means zero supplied targets; a positive numerical limit avoids division by zero.
        limit = PortfolioLimits(self.gross_cap, max(float(self.ceilings.loc[month]), 1e-12))
        return BandPolicy(self.covariance, limit, 0)(
            month, previous, target, cost_model, switched, roll_charge=roll_charge
        )


def common_risk_targets(first, second, covariance):
    """Only past-derived holdings and forecasts determine each month's matched risk."""
    risks = pd.DataFrame({name: [portfolio_risk(w, covariance[t]) for t, w in frame.iterrows()]
                          for name, frame in [("first", first), ("second", second)]}, index=first.index)
    ceiling = risks.min(axis=1)
    scaled = []
    for name, frame in [("first", first), ("second", second)]:
        scale = ceiling.div(risks[name].replace(0, np.nan)).fillna(0)
        scaled.append(frame.mul(scale, axis=0))
    return scaled, ceiling
