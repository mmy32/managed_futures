"""Export numerical checks of the production GARCH fixes using synthetic observations only.

Run from the project root:
    PYTHONPATH=. .venv/bin/python scripts/verify_garch_fixes.py --output reports/new-verification
"""

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.backtest.oos_inputs import strategy_inputs
from src.backtest.qps_baseline import build_risk_model
from src.models import MarketData
from src.risk_model import garch
from src.risk_model.daily import daily_returns

SEED = 20261116
MARKETS = ["EQ1", "EQ2", "RL", "EC", "YM"]
EXCLUDED = {"EC": "Synthetic exclusion control", "YM": "Synthetic exclusion control"}
CODE_FILES = [
    "scripts/verify_garch_fixes.py", "src/risk_model/garch.py", "src/risk_model/daily.py",
    "src/backtest/qps_baseline.py", "src/backtest/oos_inputs.py",
    "src/data_processing/strategy_inputs.py", "src/data_processing/endpoints.py",
]


def check(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": detail}


def synthetic_prices(seed):
    """Positive quote paths, an RL termination, and one deliberately missing quote."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("1999-11-01", "2002-03-29")
    common = rng.normal(0, 0.004, (len(dates), 1))
    returns = common + rng.normal(0.0001, 0.006, (len(dates), 6))
    prices = pd.DataFrame(100*np.cumprod(1+returns, axis=0), index=dates,
                          columns=["EQ1", "EQ2", "RL", "ER", "EC", "YM"])
    prices.loc["2001-10-01":, "RL"] = np.nan
    prices.loc["2001-05-16", "EQ2"] = np.nan
    return prices


def variance_checks(output):
    returns = np.array([0.03, np.nan, np.nan, -0.01, 0.02, np.nan, -0.005])
    omega, alpha, beta, start = 1e-6, 0.1, 0.8, 1e-4
    fixed = garch.garch_variance(returns, omega, alpha, beta, start)
    zero = garch.garch_variance(np.nan_to_num(returns), omega, alpha, beta, start)
    compressed = garch.garch_variance(returns[np.isfinite(returns)], omega, alpha, beta, start)
    expected, dropped, observed_count = [omega+(alpha+beta)*start], [compressed[0]], 0
    for value in returns:
        shock = expected[-1] if np.isnan(value) else value**2
        expected.append(omega+alpha*shock+beta*expected[-1])
        observed_count += int(np.isfinite(value))
        dropped.append(compressed[observed_count])
    pd.DataFrame({
        "step": np.arange(len(fixed)), "observed_return": np.r_[np.nan, returns],
        "fixed_calendar_variance": fixed, "independent_expected_variance": expected,
        "zero_imputation_counterfactual": zero, "compressed_time_counterfactual": dropped,
    }).to_csv(output / "variance_trace.csv", index=False)
    error = float(np.max(np.abs(fixed-expected)))
    return [
        check("Missing GARCH dates advance expected variance", error < 1e-15,
              f"Maximum difference from the independent recurrence: {error:.3g}."),
        check("Missing observations differ from zeros and compressed time",
              not np.isclose(fixed[3], zero[3], rtol=1e-12, atol=0)
              and not np.isclose(fixed[3], dropped[3], rtol=1e-12, atol=0),
              "See variance_trace.csv; counterfactual paths are illustrative failure modes."),
    ]


def moment_checks(output):
    target = np.array([[1.0, 0.6], [0.6, 1.0]])
    cases = [
        ("both observed", [2.0, -1.0], [[4.0, -2.0], [-2.0, 1.0]]),
        ("one missing", [2.0, np.nan], [[4.0, 2.4], [2.4, 2.08]]),
        ("both missing", [np.nan, np.nan], target),
    ]
    rows, errors = [], []
    for name, residual, expected in cases:
        actual = garch.conditional_residual_moment(residual, target)
        errors.append(float(np.max(np.abs(actual-expected))))
        for i, j in np.ndindex(actual.shape):
            rows.append({"case": name, "row": i, "column": j,
                         "fixed_moment": actual[i, j], "expected_moment": expected[i][j]})
    pd.DataFrame(rows).to_csv(output / "dcc_missing_moments.csv", index=False)
    fixed, old, trace = target.copy(), target.copy(), []
    a, b = 0.02, 0.95
    for step in range(251):
        trace.append({"missing_steps": step, "fixed_q_diagonal": fixed[0, 0],
                      "zero_shock_counterfactual_diagonal": old[0, 0]})
        fixed = (1-a-b)*target + a*garch.conditional_residual_moment([np.nan, np.nan], fixed) + b*fixed
        old = (1-a-b)*target + b*old
    pd.DataFrame(trace).to_csv(output / "dcc_missing_state_trace.csv", index=False)
    return [
        check("DCC missing residuals use conditional second moments", max(errors) < 1e-12,
              f"Maximum error across fully/partly/unobserved cases: {max(errors):.3g}."),
        check("Unavailable DCC shocks do not become observed zeros",
              np.isclose(trace[-1]["fixed_q_diagonal"], 1.0)
              and trace[-1]["zero_shock_counterfactual_diagonal"] < 0.61,
              f"After 250 missing updates: fixed Q diagonal {trace[-1]['fixed_q_diagonal']:.6f}; "
              f"zero-shock counterfactual {trace[-1]['zero_shock_counterfactual_diagonal']:.6f}. "
              "These are filter states, not portfolio returns."),
    ]


def optimizer_checks(prices, seed):
    """Mock only the explicit failure; real convergence is exercised by forecast_checks."""
    original = garch.minimize
    observed = daily_returns(prices[["EQ1", "EQ2"]]).dropna()
    failed = SimpleNamespace(success=False, fun=np.nan, x=np.array([0.97, 0.06]),
                             message="synthetic forced optimizer failure", nit=0)
    rows = []
    for name, fit in [
        ("GARCH", lambda: garch.fit_pooled_garch([observed.EQ1.to_numpy()])),
        ("DCC", lambda: garch.fit_dcc(observed, np.random.default_rng(seed))),
    ]:
        rejected = False
        with patch("src.risk_model.garch.minimize", return_value=failed):
            try:
                fit()
            except ValueError as error:
                rejected = "estimation failed" in str(error)
        rows.append(check(f"{name} rejects an unsuccessful optimizer", rejected,
                          "A scoped mock supplies success=False and a NaN objective."))
    rows.append(check("Real optimizer restored after failure checks", garch.minimize is original,
                      "All later forecast fits call the actual SciPy optimizers."))
    return rows


def fixture_inputs(prices, end):
    settings = {
        "source_selection": {"minimum_history": 6, "decision_lag_months": 2},
        "volatility_months": 12, "volatility_floor_annual": 0.02,
        "risk_model": {"type": "dcc_garch", "correlation_shrinkage": 0.1},
    }
    returns, source, known, daily = strategy_inputs(prices, MARKETS, settings, end, EXCLUDED)
    meta = pd.DataFrame({"AssetClass": ["EQ", "EQ", "FI", "FX", "EQ"]}, index=MARKETS)
    return settings, MarketData(returns, meta), source, known, daily


def source_checks(output, prices):
    _, _, source, _, daily = fixture_inputs(prices, pd.Period("2002-03", freq="M"))
    raw = daily_returns(prices[["RL", "ER"]])
    sample = daily.loc["2001-11-01":, "RL"]
    expected = raw.loc[sample.index, "ER"]
    pd.DataFrame({"selected_daily_risk_return": sample, "ER_own_daily_return": expected,
                  "raw_RL_return": raw.loc[sample.index, "RL"],
                  "selected_source": source.RL.reindex(sample.index.to_period("M")).to_numpy(),
                  }).to_csv(output / "source_continuation.csv", index_label="date")
    return [check("RL risk uses ER after RL quotes end",
                  source.loc["2001-11":"2002-03", "RL"].eq("ER").all()
                  and np.allclose(sample, expected, equal_nan=True)
                  and raw.loc[sample.index, "RL"].isna().all(),
                  f"{sample.notna().sum()} nonmissing synthetic ER risk returns remain after RL ends.")]


def forecast_case(prices, lag, end):
    settings, data, _, _, daily = fixture_inputs(prices, end)
    base = {"information_lag_months": lag, "exclude_from_strategy": EXCLUDED,
            "risk_forecast_start": "2002-01"}
    model = build_risk_model(base, settings, data.meta, daily=daily)
    vol = model.volatility(data)
    eligible = vol.loc["2002-01":end].gt(0)
    covariance, _ = model.covariances(data, eligible)
    return covariance, model.fitted_parameters(), model.coverage_diagnostics(), daily


def compare_forecasts(reference, other, cutoff):
    return max(float(np.max(np.abs(matrix-other[month])))
               for month, matrix in reference.items() if month <= cutoff)


def changed_excluded_prices(prices):
    result = prices.copy()
    result.loc[:, ["EC", "YM"]] *= 100
    weekend = pd.Timestamp("2000-03-18")
    result.loc[weekend, ["EC", "YM"]] = [1e5, 3e5]
    return result.sort_index()


def forecast_checks(output, prices):
    """Refit actual models independently for mutation, prefix and exclusion comparisons."""
    end, cutoff = pd.Period("2002-03", freq="M"), pd.Period("2002-02", freq="M")
    changed = prices.copy()
    changed.loc[cutoff.start_time:, ["EQ1", "EQ2", "ER"]] *= [2.0, 0.4, 3.0]
    changed.loc["2002-02-04":"2002-02-08", "EQ2"] = np.nan
    rows, parameters, coverage, matrices = [], [], [], []
    for lag in (1, 2):
        baseline, fitted, observed, daily = forecast_case(prices, lag, end)
        for case, frame, stop in [
            ("future mutation", changed, end),
            ("truncated history", prices.loc[:cutoff.end_time], cutoff),
        ]:
            altered, _, _, _ = forecast_case(frame, lag, stop)
            error = compare_forecasts(baseline, altered, cutoff)
            rows.append(check(f"Lag {lag}: {case} preserves earlier covariance", error < 1e-12,
                              f"Maximum covariance difference through {cutoff}: {error:.3g}."))
        if lag == 1:
            excluded, _, _, excluded_daily = forecast_case(changed_excluded_prices(prices), lag, end)
            error = compare_forecasts(baseline, excluded, end)
            rows.append(check("Excluded markets and their extra dates leave forecasts unchanged",
                              error < 1e-12 and daily.equals(excluded_daily),
                              f"Maximum covariance difference: {error:.3g}; retained daily grids equal."))
        success = [column for column in fitted if column.endswith("_success")]
        rows.append(check(f"Lag {lag}: actual annual GARCH/DCC fits converge",
                          bool(success) and fitted[success].all().all(),
                          f"Verified {len(fitted)} annual refit(s), including January information timing."))
        minimum = min(float(np.linalg.eigvalsh(matrix[:3, :3]).min())
                      for matrix in baseline.values())
        rows.append(check(f"Lag {lag}: retained forecast block is positive definite", minimum > 0,
                          f"Smallest eigenvalue across exported months: {minimum:.6g}."))
        parameters.append(fitted.assign(information_lag=lag).reset_index())
        coverage.append(observed.assign(information_lag=lag))
        for month, matrix in baseline.items():
            for i, j in np.ndindex(matrix.shape):
                matrices.append({"information_lag": lag, "holding_month": str(month),
                                 "row_market": MARKETS[i], "column_market": MARKETS[j],
                                 "annual_covariance": matrix[i, j]})
    pd.concat(parameters).to_csv(output / "fitted_parameters.csv", index=False)
    pd.concat(coverage).to_csv(output / "forecast_coverage.csv", index=False)
    pd.DataFrame(matrices).to_csv(output / "forecast_covariances.csv", index=False)
    return rows


def write_report(output, checks, seed, elapsed):
    failures = checks.loc[~checks.passed]
    status = "PASS" if failures.empty else "FAIL"
    lines = [
        "# GARCH correction verification", "",
        f"**{status}: {int(checks.passed.sum())}/{len(checks)} numerical checks passed.**", "",
        ("All observations in this package are explicitly synthetic. No uploaded monthly file "
        "or real daily futures history was fitted or scored. These checks verify code behavior; "
        "they do not establish a historical strategy advantage or validate actual market calendars."), "",
        (f"Seed: {seed}. Runtime: {elapsed:.2f} seconds. The short fixture uses a 12-month "
        "eligibility window and a six-month source-selection history to exercise actual production "
        "functions quickly. Production configuration and sealed reports are unchanged."), "",
        "| Check | Result | Numerical evidence |", "| --- | --- | --- |",
    ]
    for row in checks.itertuples(index=False):
        lines.append(f"| {row.check} | {'PASS' if row.passed else 'FAIL'} | {row.detail} |")
    lines += [
        "", "## Inspect the calculations", "",
        ("- `variance_trace.csv`: expected variance after every date, alongside explicitly labeled "
        "zero-imputation and compressed-time counterfactuals."),
        ("- `dcc_missing_moments.csv` and `dcc_missing_state_trace.csv`: analytic conditional "
        "moments and the effect of 250 unavailable shocks on the DCC filter state."),
        "- `source_continuation.csv`: selected ER risk returns remain available after RL ends.",
        ("- `fitted_parameters.csv`, `forecast_coverage.csv`, `forecast_covariances.csv`: actual "
        "SciPy estimates and production DCC forecasts on the synthetic fixture at both lags."),
        "- `checks.csv` and `manifest.json`: machine-readable outcomes, seed, versions and hashes.",
        "", ("Missing-observation conditional moments and the 21-day covariance forecast remain "
        "modeling approximations. Real-data conclusions still require original daily prices, "
        "calendar/source verification, corrected historical replay and independent evaluation."), "",
        "To reproduce from the project root, choose a new directory:", "", "```sh",
        ("PYTHONPATH=. .venv/bin/python scripts/verify_garch_fixes.py "
        "--output reports/garch_verification_new"), "```", "",
    ]
    (output / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def run_verification(output: Path, seed: int = SEED):
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    prices = synthetic_prices(seed)
    prices.to_csv(output / "synthetic_prices.csv", index_label="date")
    checks = []
    for label, operation in [
        ("variance trace", lambda: variance_checks(output)),
        ("DCC missing moments", lambda: moment_checks(output)),
        ("optimizer failure", lambda: optimizer_checks(prices, seed)),
        ("source continuation", lambda: source_checks(output, prices)),
        ("actual forecast replay", lambda: forecast_checks(output, prices)),
    ]:
        try:
            checks.extend(operation())
        except (ValueError, KeyError, IndexError, TypeError, RuntimeError) as error:
            checks.append(check(label, False, f"{type(error).__name__}: {error}"))
    table = pd.DataFrame(checks)
    table.to_csv(output / "checks.csv", index=False)
    elapsed = perf_counter()-started
    write_report(output, table, seed, elapsed)
    root = Path(__file__).resolve().parents[1]
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "input_source": "Synthetic quote paths only; no real daily data supplied or fitted",
        "seed": seed, "model_pair_sampling_seed": 0,
        "created_utc": datetime.now(UTC).isoformat(),
        "runtime_seconds": elapsed, "passed": bool(table.passed.all()),
        "versions": {"python": platform.python_version(), **{
            name: version(name) for name in ("numpy", "pandas", "scipy")}},
        "source_sha256": {name: digest(root / name) for name in CODE_FILES},
        "artifact_sha256": {path.name: digest(path) for path in sorted(output.iterdir())},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return bool(table.passed.all())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; never overwritten")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}; choose a new directory")
    passed = run_verification(args.output, args.seed)
    print(f"{'PASS' if passed else 'FAIL'}: {args.output / 'SUMMARY.md'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
