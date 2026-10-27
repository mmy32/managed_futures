"""Run the fixed v2 band grid on verified Step 2 inputs, without changing defaults."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.alpha_model import lagged
from src.backtest.band_diagnostics import paired_bootstrap, turnover_components
from src.backtest.performance import performance
from src.backtest.qps_baseline import forecasts_from
from src.backtest.qps_v2 import load_rules, qps_v2_components
from src.backtest.research_spec import run_key, validate_research_settings
from src.config import CONFIG_DIR, PROJECT_ROOT
from src.data_loader import load_asset_map
from src.models import MarketData


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_panel(path):
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.PeriodIndex(frame.index, freq="M")
    return frame


def load_inputs(reference):
    recorded = json.loads((reference / "ARTIFACT_SHA256.json").read_text())
    for name, expected in recorded.items():
        if digest(reference / name) != expected:
            raise ValueError(f"Step 2 artifact changed: {name}")
    raw_hashes = json.loads((reference / "provenance.json").read_text())["raw_hashes"]
    for name, expected in raw_hashes.items():
        if digest(PROJECT_ROOT / name) != expected:
            raise ValueError(f"Raw input changed: {name}")
    inputs = reference / "output"
    returns = read_panel(inputs / "endpoint_sensitivity_v2/returns_used.csv")
    source = read_panel(inputs / "construction/strategy_source.csv")
    known = read_panel(inputs / "construction/strategy_source_known_at.csv").iloc[:, 0]
    meta = load_asset_map()
    return returns, source, known, meta, raw_hashes


def forecasts(returns, meta, base, settings):
    parts = qps_v2_components(base, settings, load_rules(), meta)
    targets, covariance, diagnostics = forecasts_from(parts, returns, meta, base)
    volatility = parts.risk_model.volatility(MarketData(returns, meta))
    raw_targets = {}
    for name, signal in parts.signals.items():
        forecast = lagged(signal.forecast(returns), base["information_lag_months"])
        raw_targets[name] = parts.sizer.weights(forecast, volatility)[0].loc[targets[name].index]
    return targets, covariance, diagnostics, raw_targets


def export_runs(metrics, ledgers, details, gross, inputs, targets, raw_targets, out):
    sample, source = inputs
    rows, turnover_rows = [], []
    for row in metrics.itertuples(index=False):
        key = run_key(row.band, row.cost_bps, row.strategy)
        ledger, exposure = ledgers[key], details[key]["exposure"]
        for label, frame in {**details[key], "gross_contributions": gross[key]}.items():
            frame.to_csv(out / f"{key}_{label}.csv")
        trades = turnover_components(sample, exposure, ledger, source)
        trades.to_csv(out / f"{key}_turnover_components.csv")
        np.testing.assert_allclose(
            trades.sum(axis=1) * row.cost_bps / 10000, ledger.cost, atol=1e-12
        )
        np.testing.assert_allclose(
            gross[key].sum(axis=1) - details[key]["cost"].sum(axis=1), ledger.net_return, atol=1e-12
        )
        assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
        rows.append(
            dict(
                **row._asdict(),
                gross_mean_ann=ledger.gross_return.mean() * 12,
                mean_target_distance_l1=ledger.target_distance_l1.mean(),
                mean_raw_target_distance_l1=(exposure - raw_targets[row.strategy])
                .abs()
                .sum(axis=1)
                .mean(),
                mean_forecast_tracking_risk=ledger.forecast_tracking_risk.mean(),
                limit_override_months=int(ledger.limit_override.sum()),
            )
        )
        for category in trades:
            turnover_rows.append(
                dict(
                    band=row.band,
                    cost_bps=row.cost_bps,
                    strategy=row.strategy,
                    category=category,
                    turnover_ann=trades[category].mean() * 12,
                )
            )
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    pd.DataFrame(turnover_rows).to_csv(out / "turnover_breakdown.csv", index=False)
    for name in targets:
        targets[name].to_csv(out / f"{name}_targets.csv")
        raw_targets[name].to_csv(out / f"{name}_raw_targets.csv")


def verify_reference(ledgers, reference, out, reference_band):
    checks = []
    for name, ledger in ledgers.items():
        saved = reference / "output/endpoint_sensitivity_v2" / f"{name}_ledger.csv"
        if not saved.exists():
            continue  # The new 5% candidates have no Step 2 ledger.
        old = read_panel(saved)
        pd.testing.assert_frame_equal(ledger, old, check_exact=False, rtol=1e-10, atol=1e-12)
        delta = np.max(np.abs(ledger.to_numpy(dtype=float) - old.to_numpy(dtype=float)))
        checks.append(dict(run=name, maximum_absolute_difference=float(delta)))
    assert len(checks) == 8
    (out / "validation.json").write_text(
        json.dumps(
            dict(
                runs=len(ledgers),
                months=468,
                accounting_and_limits_passed=True,
                reference_band=reference_band,
                reference_checks=checks,
            ),
            indent=2,
        )
        + "\n"
    )


def paired_comparisons(ledgers, specification):
    differences, rows = {}, []
    for band in specification["bands"]:
        if band == specification["reference_band"]:
            continue
        for cost in specification["cost_scenarios_bps"]:
            for strategy in ["trend", "static"]:
                name = run_key(band, cost, strategy)
                current = ledgers[name]
                prior = ledgers[run_key(specification["reference_band"], cost, strategy)]
                delta = current.net_return - prior.net_return
                differences[name] = delta
                gross = (current.gross_return - prior.gross_return).mean() * 12
                savings = (prior.cost - current.cost).mean() * 12
                np.testing.assert_allclose(delta.mean() * 12, gross + savings, atol=1e-12)
                rows.append(
                    dict(
                        run=name,
                        band=band,
                        cost_bps=cost,
                        strategy=strategy,
                        gross_difference_ann=gross,
                        cost_savings_ann=savings,
                        net_difference_ann=delta.mean() * 12,
                    )
                )
    return pd.DataFrame(differences), pd.DataFrame(rows)


def subperiods(ledgers, specification):
    rows = []
    for band in specification["bands"]:
        for cost in specification["cost_scenarios_bps"]:
            for strategy in ["trend", "static"]:
                ledger = ledgers[run_key(band, cost, strategy)]
                prior = ledgers[run_key(specification["reference_band"], cost, strategy)]
                for start, end in specification["subperiods"]:
                    block, reference = ledger.loc[start:end], prior.loc[start:end]
                    rows.append(
                        dict(
                            band=band,
                            cost_bps=cost,
                            strategy=strategy,
                            period=f"{start}–{end}",
                            **performance(block),
                            mean_difference_ann=(block.net_return - reference.net_return).mean()
                            * 12,
                        )
                    )
    return pd.DataFrame(rows)


def uncertainty(differences, specification):
    results = []
    for block in specification["bootstrap_block_months"]:
        result = paired_bootstrap(
            differences,
            block,
            specification["bootstrap_draws"],
            specification["bootstrap_seed"] + block,
            specification["confidence"],
            specification["comparison_family_size"],
        )
        result.index.name = "run"
        results.append(result.reset_index())
    return pd.concat(results, ignore_index=True)


def reversal_diagnostics(differences, trend_targets):
    # All candidates use the same ex ante reversal dates, not their realized trade dates.
    events = (trend_targets * trend_targets.shift(1)).lt(0).any(axis=1)
    rows = []
    for offset in [-1, 0, 1]:
        selected = differences.shift(-offset).loc[events].dropna()
        for name in selected:
            rows.append(
                dict(
                    run=name,
                    relative_month=offset,
                    event_months=len(selected),
                    mean_monthly_net_difference=selected[name].mean(),
                )
            )
    return pd.DataFrame(rows), events


def screen_candidates(pairs, intervals, periods, specification):
    rows = []
    for band in specification["bands"]:
        if band == specification["reference_band"]:
            continue
        chosen = pairs[pairs.band.eq(band) & pairs.strategy.eq("trend")]
        ci = intervals[intervals.run.isin(chosen.run)]
        blocks = periods[periods.band.eq(band) & periods.strategy.eq("trend")]
        positive = (
            blocks.assign(positive=blocks.mean_difference_ann.gt(0))
            .groupby("cost_bps")
            .positive.sum()
        )
        rows.append(
            dict(
                band=band,
                material_gain_at_both_costs=bool(
                    chosen.net_difference_ann.ge(specification["minimum_mean_gain_annual"]).all()
                ),
                adjusted_intervals_positive_all_blocks=bool(ci.family_ci_low.gt(0).all()),
                stable_at_both_costs=bool(
                    positive.ge(specification["minimum_positive_subperiods"]).all()
                ),
                positive_subperiods={str(k): int(v) for k, v in positive.items()},
            )
        )
    return rows


def save_diagnostics(ledgers, targets, specification, out):
    differences, pairs = paired_comparisons(ledgers, specification)
    periods = subperiods(ledgers, specification)
    intervals = uncertainty(differences, specification)
    reversals, events = reversal_diagnostics(differences, targets["trend"])
    for name, frame in [
        ("paired_differences", differences),
        ("paired_comparison", pairs),
        ("subperiods", periods),
        ("paired_intervals", intervals),
        ("reversal_diagnostics", reversals),
    ]:
        frame.to_csv(out / f"{name}.csv", index=name == "paired_differences")
    events.rename("any_target_reversal").to_csv(out / "reversal_months.csv")
    (out / "candidate_screen.json").write_text(
        json.dumps(
            screen_candidates(pairs, intervals, periods, specification),
            indent=2,
        )
        + "\n"
    )


def main(reference, out):
    from run_risk_research import evaluate

    if out.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    specification = json.loads((CONFIG_DIR / "band_experiment.json").read_text())
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    settings.update(
        bands=specification["bands"], cost_scenarios_bps=specification["cost_scenarios_bps"]
    )
    validate_research_settings(settings)
    base = json.loads((PROJECT_ROOT / settings["base_config"]).read_text())
    returns, source, known, meta, raw_hashes = load_inputs(reference)
    out.mkdir(parents=True)
    (out / "trial_specification.json").write_text(json.dumps(specification, indent=2) + "\n")
    (out / "risk_settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (out / "raw_hashes.json").write_text(json.dumps(raw_hashes, indent=2) + "\n")
    targets, covariance, diagnostics, raw_targets = forecasts(returns, meta, base, settings)
    diagnostics.to_csv(out / "target_diagnostics.csv", index=False)
    sample = returns.loc[base["start"] : base["end"]]
    metrics, alphas, ledgers, details, gross, failures = evaluate(
        sample,
        source.loc[sample.index],
        known.loc[sample.index],
        targets,
        covariance,
        settings,
        out,
    )
    assert not failures and len(metrics) == 12
    export_runs(
        metrics,
        ledgers,
        details,
        gross,
        (sample, source.loc[sample.index]),
        targets,
        raw_targets,
        out,
    )
    alphas.to_csv(out / "alpha.csv", index=False)
    verify_reference(ledgers, reference, out, specification["reference_band"])
    save_diagnostics(ledgers, targets, specification, out)
    print(
        metrics[["band", "cost_bps", "strategy", "cagr", "sharpe", "turnover_ann"]].to_string(
            index=False
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.reference.resolve(), args.output.resolve())
