"""Run and seal the fixed Lecture 9 experiment on verified historical inputs."""

import argparse
import importlib.metadata
import json
import platform
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from freeze_prospective import digest, frozen_files, verify
from run_band_experiment import load_inputs, read_panel

from src.backtest.attribution import class_attribution
from src.backtest.engine import simulate
from src.backtest.band_diagnostics import paired_bootstrap, turnover_components
from src.backtest.pc_experiment import (
    CommonRiskPolicy, ScheduledPolicy, case_metrics, common_risk_targets,
    paired_results, policies, run_case, select_policy, selection_schedule, validate_specification,
)
from src.backtest.qps_baseline import (
    configured_components, forecasts_from, portfolio_limits, rescaled_components,
)
from src.backtest.sample_diagnostics import risk_diagnostics
from src.config import CONFIG_DIR, PROJECT_ROOT
from src.data_processing.strategy_inputs import load_daily_returns
from src.portfolio_construction import BandPolicy
from src.portfolio_construction.trade.cost_aware import CostAwarePolicy
from src.transaction_cost_model import LinearBpsCost


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(reference, output):
    if output.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    spec = json.loads((CONFIG_DIR / "pc_experiment.json").read_text())
    validate_specification(spec)
    inputs = load_inputs(reference)
    risk = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    # The shared rescale shadow portfolio uses the same cost assumption as this experiment.
    risk.update(primary_cost_bps=spec["cost_bps"], cost_scenarios_bps=[spec["cost_bps"]])
    base = json.loads((PROJECT_ROOT / risk["base_config"]).read_text())
    output.mkdir(parents=True)
    files = frozen_files(PROJECT_ROOT)
    with zipfile.ZipFile(output / "source_snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(PROJECT_ROOT / name, name)
    write_json(output / "specification.json", dict(experiment=spec, baseline=base, risk=risk))
    write_json(output / "pre_run_record.json", dict(
        created_utc=datetime.now(timezone.utc).isoformat(), files=files, raw_inputs=inputs[-1],
        reference_manifest_sha256=digest(reference / "ARTIFACT_SHA256.json"),
        package_versions={n: importlib.metadata.version(n) for n in
                          ["numpy", "pandas", "scipy", "cvxpy", "clarabel", "pytest"]},
        python=platform.python_version(),
    ))
    return spec, base, risk, inputs


def forecasts(inputs, base, risk, lag, variant, output, daily=None, model_cache=None):
    started = perf_counter()
    print(f"Computing shared forecasts: {variant}, lag {lag}", flush=True)
    returns, source, known, meta, _ = inputs
    base = dict(base, information_lag_months=lag)
    settings = dict(risk)
    if variant == "rolling_reference":
        settings.pop("trend_signal_by_asset_class", None)
        settings["risk_model"] = {"type": "rolling"}
    parts = configured_components(base, settings, meta, daily=daily)
    if settings.get("risk_model", {}).get("type") == "dcc_garch" and model_cache is not None:
        if "dcc" in model_cache:
            parts = replace(parts, risk_model=model_cache["dcc"].variant(lag=lag))
        else:
            model_cache["dcc"] = parts.risk_model
    parts = rescaled_components(parts, returns, meta, base, settings, source, known)
    targets, covariance, diagnostics = forecasts_from(parts, returns, meta, base)
    target = targets["trend"]
    output.mkdir(parents=True)
    write_json(output / "forecast_settings.json", dict(base=base, risk=settings))
    diagnostics.to_csv(output / "target_diagnostics.csv", index=False)
    target.to_csv(output / "targets.csv.gz")
    np.savez_compressed(output / "covariance.npz", **{str(t): m for t, m in covariance.items()})
    write_json(output / "forecast_profile.json", dict(
        elapsed_seconds=perf_counter() - started, covariance_months=len(covariance),
        reused_across_policies=True,
    ))
    sample = returns.loc[target.index]
    sample.to_csv(output / "returns_used.csv.gz")
    source.loc[target.index].to_csv(output / "sources.csv.gz")
    known.loc[target.index].to_csv(output / "source_known_at.csv")
    return sample, target, covariance, source.loc[target.index], known.loc[target.index], meta


def export_case(name, result, data, output, elapsed, policy):
    ledger, gross, details = result
    sample, target, covariance, source, known, meta = data
    ledger.to_csv(output / f"{name}_ledger.csv.gz")
    for label, frame in details.items():
        frame.to_csv(output / f"{name}_{label}.csv.gz")
    turnover_components(sample, details["exposure"], ledger, source).to_csv(
        output / f"{name}_turnover.csv.gz"
    )
    class_net, class_exposure, class_risk, classes = class_attribution(
        ledger, gross, details, covariance, meta
    )
    for label, frame in [("class_net", class_net), ("class_exposure", class_exposure),
                         ("class_risk", class_risk), ("classes", classes),
                         ("risk", risk_diagnostics(ledger)[0])]:
        frame.to_csv(output / f"{name}_{label}.csv")
    row = case_metrics(name, ledger)
    row["elapsed_seconds"] = elapsed
    if isinstance(policy, CostAwarePolicy):
        row.update(solve_count=policy.solve_count, problem_builds=len(policy.problems),
                   cached_factors=len(policy.factor_cache))
    return row


def execute(name, policy, data, spec, output):
    started = perf_counter()
    try:
        result = run_case(*data[:5], policy, spec)
        row = export_case(name, result, data, output, perf_counter() - started, policy)
        row["within_runtime_budget"] = row["elapsed_seconds"] <= spec["runtime_budget_seconds_per_fixed_case"]
    except Exception as error:
        write_json(output / "failure.json", dict(
            run=name, error=repr(error), inputs=getattr(policy, "failure", None)
        ))
        raise
    print(f"Completed {output.name}/{name}: {row['elapsed_seconds']:.2f}s", flush=True)
    return result, row


def comparisons(results, spec, output):
    ledgers = {name: result[0] for name, result in results.items()}
    start = ledgers["band10"].index[spec["selection_minimum_months"]]
    differences, pairs = paired_results(ledgers, start)
    differences.to_csv(output / "paired_differences.csv")
    pairs.to_csv(output / "paired_comparison.csv", index=False)
    intervals = []
    for block in spec["bootstrap_blocks"]:
        interval = paired_bootstrap(
            differences, block, spec["bootstrap_draws"], spec["bootstrap_seed"] + block,
            spec["confidence"], spec["comparison_family_size"],
        )
        intervals.append(interval.rename_axis("run").reset_index())
    pd.concat(intervals, ignore_index=True).to_csv(output / "paired_intervals.csv", index=False)
    pd.DataFrame([case_metrics(name, ledger.loc[start:]) for name, ledger in ledgers.items()]).to_csv(
        output / "scored_comparison.csv", index=False
    )
    return pairs


def primary_experiment(data, risk, spec, output):
    limits = portfolio_limits(risk)
    policy_set = policies(data[2], limits, spec)
    results, rows = {}, []
    for name, policy in policy_set.items():
        results[name], row = execute(name, policy, data, spec, output)
        rows.append(row)
    ledgers = {name: result[0] for name, result in results.items()}
    schedule, trail = selection_schedule(ledgers, spec)
    schedule.to_csv(output / "selection_schedule.csv")
    trail.to_csv(output / "selection_scores.csv", index=False)
    selected = ScheduledPolicy(policies(data[2], limits, spec), schedule)
    results["walkforward"], row = execute("walkforward", selected, data, spec, output)
    rows.append(row)
    pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
    comparisons(results, spec, output)
    choice, scores = select_policy(ledgers, spec, len(schedule))
    write_json(output / "final_selection.json", dict(selected=choice, scores=scores))
    return results, choice


def secondary_experiment(data, risk, spec, selected, output):
    policy_set = policies(data[2], portfolio_limits(risk), spec)
    results, rows = {}, []
    for name in dict.fromkeys(["band10", "full", selected]):
        results[name], row = execute(name, policy_set[name], data, spec, output)
        rows.append(row)
    pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
    comparisons(results, spec, output)


def verify_reference(data, risk, reference, output):
    """Reproduce the historical baseline at its original cost and information lag."""
    ledger, _ = simulate(
        data[0], data[1], LinearBpsCost(2), data[3], source_known_at=data[4],
        position_policy=BandPolicy(data[2], portfolio_limits(risk), 0.1),
    )
    expected = read_panel(reference / "output/endpoint_sensitivity/correlated_band10_2bps_trend_ledger.csv")
    fields = ["nav_end", "net_return", "turnover", "cost", "gross_return", "gross_after_cost"]
    pd.testing.assert_frame_equal(ledger[fields], expected[fields], rtol=1e-10, atol=1e-12)
    write_json(output / "reference_reproduction.json", dict(
        passed=True, cost_bps=2, information_lag_months=1,
        maximum_difference=float(np.abs(ledger[fields] - expected[fields]).to_numpy().max()),
    ))


def matched_risk_experiment(data, results, risk, spec, output):
    output.mkdir()
    targets, ceilings = common_risk_targets(
        results["band10"][2]["exposure"], results["walkforward"][2]["exposure"], data[2]
    )
    ceilings.to_csv(output / "common_risk_ceiling.csv")
    matched, rows = {}, []
    for name, target in zip(["band10", "walkforward"], targets, strict=True):
        changed = (data[0], target, *data[2:])
        policy = CommonRiskPolicy(data[2], risk["gross_cap"], ceilings)
        matched[name], row = execute(name, policy, changed, spec, output)
        rows.append(row)
        np.testing.assert_allclose(matched[name][0].forecast_after_cost, ceilings, atol=1e-9)
    pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
    comparisons(matched, spec, output)


def seal(reference, output, selected, spec):
    record = json.loads((output / "pre_run_record.json").read_text())
    record.update(
        source_snapshot_sha256=digest(output / "source_snapshot.zip"),
        reference_manifests={str((reference / "ARTIFACT_SHA256.json").relative_to(PROJECT_ROOT)):
                             digest(reference / "ARTIFACT_SHA256.json")},
        protocol=dict(
            status="frozen_development_decision_awaiting_untouched_data", selected_policy=selected,
            development_end="2014-12", cost_bps=spec["cost_bps"],
            information_lag_months=spec["primary_information_lag_months"],
            solver=spec["solver"], evaluation_start=None, evaluation_months=36,
            initial_positions="flat", primary_comparator="configured DCC-GARCH TREND, 10% bands",
            primary_endpoint="Annualized paired mean net return: frozen selected policy minus configured DCC-GARCH TREND with 10% bands at 1.5 bps and lag 2. No calibration-period exclusion in the fresh evaluation.",
            activation="Declare dates, warmup, data provenance and execution convention before outcomes.",
            early_stopping="No performance-based stopping, retuning or calendar deletion.",
        ), prospective_observations=0, independent_validation_complete=False,
    )
    write_json(output / "freeze.json", record)
    verify(PROJECT_ROOT, output)


def report(output, selected, spec):
    primary = output / "configured_lag2"
    metrics = pd.read_csv(primary / "scored_comparison.csv").set_index("run")
    pairs = pd.read_csv(primary / "paired_comparison.csv").set_index("run")
    lines = ["# Lecture 9 portfolio-construction experiment", "",
             f"Development selection for the next period: **{selected}**. Production defaults are preserved.",
             "", "Primary scores cover 1986-2014 after ten years of calibration history; all history is development data.",
             "The primary case uses a two-month information lag and 1.5 bps per absolute one-way turnover.",
             "", "| Policy | Net annual mean | CAGR | Volatility | Max drawdown | Annual turnover |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in metrics.iterrows():
        lines.append(f"| {name} | {row.mean_ann:.2%} | {row.cagr:.2%} | {row.vol_ann:.2%} | "
                     f"{row.max_drawdown:.2%} | {row.turnover_ann:.2f}x |")
    lines += ["", "| Comparison with bands | Gross change (bps/year) | Cost saving | Net change |",
              "| --- | ---: | ---: | ---: |"]
    for name, row in pairs.iterrows():
        lines.append(f"| {name} | {row.gross_difference_ann * 10000:.2f} | "
                     f"{row.cost_savings_ann * 10000:.2f} | {row.net_difference_ann * 10000:.2f} |")
    lines += ["", "See `configured_lag2/paired_intervals.csv` for paired 6/12-month block intervals and family-adjusted intervals.",
              "Selection scores use only prior completed months; the walk-forward path carries actual holdings across switches.",
              "The fixed-gamma comparisons and selection remain exploratory because these years were already inspected.",
              "", "`common_risk/` replays the two original paths' ex ante directions at the same after-fee forecast risk, with new trades and NAV.",
              "`configured_lag1/` and `rolling_reference_lag2/` evaluate the primary-selected fixed policy without retuning.",
              "`rolling_reference_lag1/reference_reproduction.json` checks the archived 2-bps baseline.",
              "", "Results remain conditional on the unverified March 1997 endpoints and vendor price-history conventions.",
              "This is a zero-cash, trade-only monthly proxy; contract rolls, executable fills and capacity are not established.",
              "", "The source/config release is sealed in `freeze.json` and `source_snapshot.zip`. No untouched evaluation data were supplied; independent validation remains pending."]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n")


def main(reference, output):
    started = perf_counter()
    spec, base, risk, inputs = prepare(reference, output)
    try:
        primary = output / "configured_lag2"
        daily = (load_daily_returns(inputs[0].columns)
                 if risk.get("risk_model", {}).get("type") == "dcc_garch" else None)
        model_cache = {}
        data = forecasts(inputs, base, risk, spec["primary_information_lag_months"],
                         "configured", primary, daily, model_cache)
        results, selected = primary_experiment(data, risk, spec, primary)
        matched_risk_experiment(data, results, risk, spec, output / "common_risk")
        for variant, lag in [("configured", spec["sensitivity_information_lag_months"]),
                             ("rolling_reference", spec["primary_information_lag_months"])]:
            folder = output / f"{variant}_lag{lag}"
            secondary = forecasts(inputs, base, risk, lag, variant, folder, daily, model_cache)
            secondary_experiment(secondary, risk, spec, selected, folder)
        archived = output / "rolling_reference_lag1"
        verify_reference(forecasts(inputs, base, risk, 1, "rolling_reference", archived),
                         risk, reference, archived)
        seal(reference, output, selected, spec)
        report(output, selected, spec)
        write_json(output / "validation.json", dict(
            status="complete", accounting_and_limits_passed=True, reference_hashes_verified=True,
            common_risk_matched=True, source_freeze_verified=True,
            independent_validation_complete=False, elapsed_seconds=perf_counter() - started,
        ))
    except Exception as error:
        write_json(output / "failure.json", dict(status="failed", error=repr(error)))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.reference.resolve(), args.output.resolve())
