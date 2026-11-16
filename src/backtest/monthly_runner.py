"""Matched monthly risk/sizing comparisons and independent exported-account checks."""

from dataclasses import replace

import numpy as np
import pandas as pd

from src.backtest.engine import simulate
from src.backtest.performance import performance
from src.backtest.qps_baseline import forecasts_from, hold_adjustment, qps_components
from src.config import PROJECT_ROOT
from src.data_loader import load_full_sample_returns
from src.models import MarketData
from src.portfolio_construction import BandPolicy
from src.risk_model import (
    RollingCovarianceRiskModel,
    ScaledRiskModel,
    standardized_returns,
    trailing_scale,
)
from src.risk_model.monthly_garch import MonthlyDccGarchRiskModel
from src.transaction_cost_model import LinearBpsCost


class CommonEligibilityRiskModel:
    """Apply one prior-only eligibility mask to both covariance estimators."""

    def __init__(self, model, common):
        self.model, self.common = model, common

    def volatility(self, data):
        return self.model.volatility(data).where(self.common)

    def covariances(self, data, eligible):
        if (eligible & ~self.common.reindex(eligible.index)).any().any():
            raise ValueError("Covariance eligibility differs from the matched monthly universe")
        return self.model.covariances(data, eligible)


def monthly_models(returns, meta, spec):
    options = {"window": spec["volatility_months"], "lag": spec["information_lag_months"],
                   "volatility_floor": spec["volatility_floor_annual"],
                   "correlation_shrinkage": spec["correlation_shrinkage"]}
    garch = MonthlyDccGarchRiskModel(
        meta.AssetClass, **options,
        min_fit_observations=spec["garch_min_fit_observations"],
        pair_count=spec["dcc_pair_count"], seed=spec["seed"], forecast_start=spec["start"],
    )
    rolling = RollingCovarianceRiskModel(**options)
    data = MarketData(returns, meta)
    print("Fitting monthly GARCH/DCC on expanding past monthly history", flush=True)
    garch_vol, rolling_vol = garch.volatility(data), rolling.volatility(data)
    common = garch_vol.gt(0) & rolling_vol.gt(0)
    return {"rolling": CommonEligibilityRiskModel(rolling, common),
            "monthly_dcc_garch": CommonEligibilityRiskModel(garch, common)}, garch, common


def trend_components(base, risk, meta, model):
    parts = qps_components({**base, "hold_sizing": "inverse_vol"}, risk, meta, model)
    return replace(parts, signals={"trend": parts.signals["trend"]})


def simulate_parts(parts, returns, meta, base, risk, *, liquidate=True):
    targets, covariance, diagnostics = forecasts_from(parts, returns, meta, base)
    sample = returns.loc[base["start"]:base["end"]]
    details = {}
    ledger, _ = simulate(
        sample, targets["trend"], LinearBpsCost(risk["primary_cost_bps"]),
        position_policy=BandPolicy(covariance, parts.limits, risk["primary_band"]),
        instrument_details=details, liquidate=liquidate,
    )
    return ledger, details["exposure"], targets["trend"], covariance, diagnostics


def calibrated_components(parts, returns, meta, base, risk, spec):
    # Only lagged shadow observations affect the scale. Terminal shadow liquidation
    # is disabled: it is not a transaction an ongoing calibration account made.
    shadow, _, _, _, _ = simulate_parts(parts, returns, meta, base, risk, liquidate=False)
    options = spec["rescale"]
    scale = trailing_scale(standardized_returns(shadow), options["window"],
                           options["minimum"], base["information_lag_months"])
    scale = scale.reindex(returns.index).fillna(1.0)
    return replace(parts, risk_model=ScaledRiskModel(parts.risk_model, scale)), scale, shadow


def period_metrics(ledger, risk_name, portfolio, spec):
    start, boundary, end = (pd.Period(spec[key], "M")
                            for key in ("start", "development_end", "end"))
    periods = {"in_sample": (start, boundary), "test_period": (boundary+1, end),
               "full_sample": (start, end)}
    rows = []
    for label, (first, last) in periods.items():
        section = ledger.loc[first:last]
        if not section.index.equals(pd.period_range(first, last, freq="M")):
            raise ValueError(f"Incomplete monthly portfolio calendar for {label}")
        rows.append(dict(risk_model=risk_name, portfolio=portfolio, period=label,
                         start=str(first), end=str(last), **performance(section)))
    return rows


def export_comparison(returns, meta, base, risk, spec, output):
    models, garch, common = monthly_models(returns, meta, spec)
    common.to_csv(output / "common_eligibility.csv.gz")
    print(f"Common eligible markets at {spec['start']}: "
          f"{int(common.loc[spec['start']].sum())}; fewer than "
          f"{base['minimum_instruments']} means a flat portfolio", flush=True)
    rows = []
    for risk_name, model in models.items():
        parts = trend_components(base, risk, meta, model)
        parts, scale, shadow = calibrated_components(parts, returns, meta, base, risk, spec)
        scale.to_csv(output / f"{risk_name}_rescale.csv", header=["scale"])
        shadow.to_csv(output / f"{risk_name}_shadow_ledger.csv.gz")
        for portfolio in ("inverse_vol", "hrp_within_class"):
            case = replace(parts, adjustment=hold_adjustment(portfolio))
            ledger, exposure, target, covariance, diagnostics = simulate_parts(
                case, returns, meta, base, risk
            )
            name = f"{risk_name}_{portfolio}"
            for label, frame in (("ledger", ledger), ("exposure", exposure), ("target", target)):
                frame.to_csv(output / f"{name}_{label}.csv.gz", float_format="%.17g")
            diagnostics.to_csv(output / f"{name}_diagnostics.csv", index=False)
            rows.extend(period_metrics(ledger, risk_name, portfolio, spec))
            print(f"Completed {risk_name}, {portfolio}: {len(ledger)} months", flush=True)
        np.savez_compressed(output / f"{risk_name}_covariances.npz",
                            matrices=np.stack([covariance[month] for month in ledger.index]))
    garch.fitted_parameters().to_csv(output / "model_parameters.csv", index=False)
    garch.coverage_diagnostics().to_csv(output / "model_coverage.csv.gz", index=False)
    return pd.DataFrame(rows)


def strict_checks(returns, meta, base, risk, spec):
    """Attempt required rolling-risk shadow on all declared markets; never fill P&L."""
    model = RollingCovarianceRiskModel(
        window=spec["volatility_months"], lag=spec["information_lag_months"],
        volatility_floor=spec["volatility_floor_annual"],
        correlation_shrinkage=spec["correlation_shrinkage"],
    )
    rows = []
    for label, start in (("full_sample", base["start"]),
                         ("test_period", str(pd.Period(spec["development_end"], "M")+1))):
        period_base = {**base, "start": start}
        parts = trend_components(period_base, risk, meta, model)
        try:
            # This is an input/accounting diagnostic of the mandatory unscaled
            # baseline shadow, not a complete all-market GARCH/HRP assessment.
            simulate_parts(parts, returns, meta, period_base, risk, liquidate=False)
        except ValueError as error:
            if not str(error).startswith("Missing held return"):
                raise
            rows.append({"case": f"{label}_rolling_inverse_vol_shadow",
                             "start": start, "end": base["end"], "status": "BLOCKED", "error": str(error)})
        else:
            rows.append({"case": f"{label}_rolling_inverse_vol_shadow",
                             "start": start, "end": base["end"], "status": "PASSED_INPUT_CHECK", "error": ""})
    return rows


def read_monthly(path):
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.PeriodIndex(frame.index, freq="M")
    return frame


def independent_case_check(ledger, exposure, returns, matrices, spec):
    """Reconstruct account arithmetic from executed exposures, without simulate()."""
    calendar = pd.period_range(spec["start"], spec["end"], freq="M")
    if not ledger.index.equals(calendar) or not exposure.index.equals(calendar):
        raise ValueError("Exported ledger/holdings do not match the declared calendar")
    if not exposure.columns.equals(returns.columns) or len(matrices) != len(calendar):
        raise ValueError("Exported return, exposure and covariance dimensions differ")
    previous, nav = np.zeros(len(returns.columns)), 1.0
    for i, month in enumerate(calendar):
        weights, values = exposure.loc[month].to_numpy(float), returns.loc[month].to_numpy(float)
        if (np.isnan(values) & (np.abs(weights) > 1e-14)).any():
            raise ValueError(f"Unknown held monthly return at {month}")
        if not np.isfinite(weights).all() or np.isinf(values).any():
            raise ValueError("Nonfinite exported holdings/returns")
        values = np.where(np.isfinite(values), values, 0.0)
        trades = np.abs(weights-previous).sum()
        terminal = np.abs(weights*(1+values)).sum() if i == len(calendar)-1 else 0.0
        gross = float(weights @ values)
        cost = (trades+terminal)*spec["cost_bps"]/10000
        net = gross-cost
        actual = ledger.loc[month]
        np.testing.assert_allclose(
            [actual.gross_return, actual.cost, actual.net_return, actual.turnover,
             actual.nav_start, actual.nav_end],
            [gross, cost, net, trades+terminal, nav, nav*(1+net)], atol=1e-10, rtol=1e-10,
        )
        _check_executed_limits(weights, matrices[i], trades, spec)
        previous, nav = weights*(1+values)/(1+net), nav*(1+net)


def _check_executed_limits(weights, matrix, trades, spec):
    denominator = 1-trades*spec["cost_bps"]/10000
    gross = np.abs(weights).sum()/denominator
    risk = np.sqrt(max(float(weights @ matrix @ weights), 0.0))/denominator
    if gross > spec["gross_cap"]+1e-9 or risk > spec["portfolio_risk_ceiling"]+1e-9:
        raise ValueError("Exported holdings breach after-cost monthly decision limits")


def verify_exported_accounting(output, spec):
    # Course returns stay in the ignored input directory. Reconstruct the exact
    # declared panel from those supplied inputs instead of publishing a copy.
    audit = pd.read_csv(output / "universe_audit.csv", index_col=0)
    selected = list(audit.index[audit.included_coverage])
    returns = load_full_sample_returns(PROJECT_ROOT / spec["monthly_returns"], units="decimal")[selected]
    metrics = pd.read_csv(output / "metrics.csv")
    checks = []
    for risk_name in ("rolling", "monthly_dcc_garch"):
        with np.load(output / f"{risk_name}_covariances.npz") as payload:
            matrices = payload["matrices"]
        for portfolio in ("inverse_vol", "hrp_within_class"):
            name = f"{risk_name}_{portfolio}"
            ledger = read_monthly(output / f"{name}_ledger.csv.gz")
            exposure = read_monthly(output / f"{name}_exposure.csv.gz")
            independent_case_check(ledger, exposure, returns, matrices, spec)
            for row in period_metrics(ledger, risk_name, portfolio, spec):
                match = metrics[(metrics.risk_model == risk_name) &
                                (metrics.portfolio == portfolio) & (metrics.period == row["period"])]
                if len(match) != 1:
                    raise ValueError("Missing or duplicated exported metric row")
                for field in ("mean_ann", "vol_ann", "sharpe", "cagr", "max_drawdown"):
                    np.testing.assert_allclose(row[field], match.iloc[0][field], atol=1e-11)
            checks.append({"check": name, "status": "PASS",
                               "detail": "593-month accounting, held returns, limits and period metrics"})
    return checks
