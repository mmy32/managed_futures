"""Load → signal/risk → size → bands/limits → simulate → summarize → report."""

import argparse
import hashlib
import json
import platform
import shutil
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import statsmodels
from research_report import make_charts, write_blocked_report, write_report

from src.backtest.engine import performance, regression_alpha, simulate
from src.backtest.qps_baseline import build_forecasts, eligibility, portfolio_limits
from src.backtest.research_statistics import (
    class_attribution,
    class_portfolios,
    rank_autocorrelation,
    risk_diagnostics,
    sample_audit,
    stability_summary,
)
from src.config import (
    ASSET_MAP_PATH,
    CONFIG_DIR,
    FUTURES_UNDERLYING_DIR,
    PROJECT_ROOT,
    QPS_OUTPUT_DIR,
    QPS_REPORT_DIR,
    RAW_DATA_DIR,
)
from src.data_processing.endpoint_sensitivity import apply_endpoint_assumption
from src.data_processing.strategy_inputs import load_strategy_inputs
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost

ROOT = PROJECT_ROOT
OUT = QPS_OUTPUT_DIR / "risk"


def key(band, cost, strategy):
    return f"correlated_band{round(band * 100):02d}_{cost}bps_{strategy}"


def evaluate(sample, source, known, targets, covariance, settings, out=None):
    out = OUT if out is None else out
    metrics, alphas, ledgers, details, contributions = [], [], {}, {}, {}
    failures, blocked_holdings = [], []
    for band in settings["bands"]:
        for cost in settings["cost_scenarios_bps"]:
            pair = {}
            for strategy in ["trend", "static"]:
                name = key(band, cost, strategy)
                instrument = {}
                policy = BandPolicy(covariance, portfolio_limits(settings), band)
                try:
                    ledger, gross = simulate(
                        sample,
                        targets[strategy],
                        LinearBpsCost(cost),
                        source,
                        position_policy=policy,
                        source_known_at=known,
                        instrument_details=instrument,
                    )
                except ValueError as error:
                    if not str(error).startswith("Missing held return"):
                        raise
                    failures.append(
                        {"strategy": strategy, "band": band, "cost_bps": cost, "error": str(error)}
                    )
                    month = max(policy.executed)
                    for asset, exposure in zip(sample.columns, policy.executed[month]):
                        if abs(exposure) > 1e-14 and pd.isna(sample.loc[month, asset]):
                            blocked_holdings.append(
                                {
                                    "run": name,
                                    "month": str(month),
                                    "instrument": asset,
                                    "exposure": exposure,
                                }
                            )
                    continue
                ledger.to_csv(out / f"{name}_ledger.csv")
                ledgers[name], details[name], contributions[name] = ledger, instrument, gross
                pair[strategy] = ledger.net_return
                timeline, calibration = risk_diagnostics(ledger)
                timeline.to_csv(out / f"{name}_risk_through_time.csv")
                metrics.append(
                    dict(
                        model="correlated",
                        band=band,
                        cost_bps=cost,
                        strategy=strategy,
                        **performance(ledger),
                        **calibration,
                        max_gross_after_cost=ledger.gross_after_cost.max(),
                        max_forecast_after_cost=ledger.forecast_after_cost.max(),
                        gross_breaches=int(ledger.gross_limit_breach.sum()),
                        risk_breaches=int(ledger.risk_limit_breach.sum()),
                    )
                )
            for lag in [3, 6, 12] if len(pair) == 2 else []:
                alpha, _ = regression_alpha(pair["trend"], pair["static"].to_frame("STATIC"), lag)
                alphas.append(
                    dict(
                        band=band,
                        cost_bps=cost,
                        correlation=pair["trend"].corr(pair["static"]),
                        **alpha,
                    )
                )
    if failures:
        pd.DataFrame(blocked_holdings).to_csv(out / "blocked_holdings.csv", index=False)
        pd.DataFrame(failures).to_csv(out / "blocked_attempts.csv", index=False)
    return pd.DataFrame(metrics), pd.DataFrame(alphas), ledgers, details, contributions, failures


def archive_previous_outputs(out=OUT, report_names=("REPORT.md", "REPORT.html")):
    """Keep old-period or partial results from masquerading as the current run."""
    archive = QPS_OUTPUT_DIR / "prior_runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    paths = [
        p
        for p in out.iterdir()
        if p.is_file() and p.name not in ["validation.json", "legacy_reproduction.json"]
    ]
    if paths:
        archive.mkdir(parents=True)
        for path in paths:
            shutil.move(str(path), archive / path.name)
        for name in report_names:
            if (QPS_REPORT_DIR / name).exists():
                shutil.copy2(QPS_REPORT_DIR / name, archive / name)


def endpoint_candidates(out=OUT):
    """Review-only values, never consumed by the trading data loader."""
    rows = []
    for asset in ["DT", "GS", "LX", "SS"]:
        raw = pd.read_csv(FUTURES_UNDERLYING_DIR / f"{asset}.csv", index_col=0, parse_dates=True)
        previous = raw.loc["1997-02", "Close"].iloc[-1]
        endpoint = raw.loc["1997-03-27", "Close"]
        following = raw.loc["1997-04", "Close"].iloc[-1]
        for month, value in [
            ("1997-03", endpoint / previous - 1),
            ("1997-04", following / endpoint - 1),
        ]:
            rows.append(
                {
                    "instrument": asset,
                    "month": month,
                    "proposed_return": value,
                    "assumed_march_endpoint": "1997-03-27",
                    "applied": False,
                    "evidence_status": "Venue closure unverified; research assumption requires explicit selection",
                }
            )
    pd.DataFrame(rows).to_csv(out / "proposed_endpoint_returns.csv", index=False)


def audit_data(returns, source, known, schedule, eligible, base, settings, out=OUT):
    audit = sample_audit(returns, eligible, base)
    index = pd.period_range(base["start"], base["end"], freq="M")
    assert (known.to_numpy() < returns.index.to_timestamp().to_numpy()).all()
    for name in base["exclude_from_strategy"]:
        assert not eligible[name].any()
    assert not {"ER", "EN", "ES", "SC"} & set(returns.columns)
    changes = pd.read_csv(QPS_OUTPUT_DIR / "construction/return_changes.csv")
    assert len(changes) == 8
    dates = pd.PeriodIndex(changes.month, freq="M")
    audit.update(
        retained_columns=len(returns.columns),
        excluded_columns=list(base["exclude_from_strategy"]),
        observed_instrument_returns=int(returns.loc[index].count().sum()),
        eligible_instrument_observations=int(eligible.loc[index].sum().sum()),
        endpoint_return_corrections_in_sample=int(
            ((dates >= index[0]) & (dates <= index[-1])).sum()
        ),
        source_switch_month=str(schedule.loc[schedule.source.eq("ER"), "month"].iloc[0]),
        source_known_before_all_months=True,
        duplicate_columns_absent=["ER", "EN", "ES", "SC"],
    )
    (out / "sample_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    if not audit["start_ready"]:
        print(
            f"SAMPLE READINESS FAILED: {audit['eligible_at_start']} eligible at {audit['start']}; "
            f"need {audit['minimum_required']}. {audit['treatment']}",
            flush=True,
        )
    return audit


def write_manifest(settings, base, original_hashes, out=OUT):
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in original_hashes.items()
    )
    paths = (
        list((ROOT / "scripts").glob("*.py"))
        + sorted((ROOT / "src").rglob("*.py"))
        + list(CONFIG_DIR.glob("*.json"))
    )
    paths += [
        QPS_OUTPUT_DIR / "construction/monthly_returns_strategy.csv",
        QPS_OUTPUT_DIR / "construction/strategy_source.csv",
        out / "returns_used.csv",
    ]
    manifest = {
        "config": settings,
        "base_config": base,
        "sources_unchanged": True,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "statsmodels": statsmodels.__version__,
        },
        "files": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        "data_hashes": original_hashes,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(endpoint_sensitivity=False):
    out = QPS_OUTPUT_DIR / "endpoint_sensitivity" if endpoint_sensitivity else OUT
    report_path = QPS_REPORT_DIR / "REPORT.md"
    out.mkdir(parents=True, exist_ok=True)
    archive_previous_outputs(out, (report_path.name, report_path.with_suffix(".html").name))
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    base = json.loads((ROOT / settings["base_config"]).read_text())
    original_hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in RAW_DATA_DIR.rglob("*")
        if p.is_file()
    }
    returns, source, known, schedule = load_strategy_inputs(settings, write=True)
    assumption = None
    if endpoint_sensitivity:
        assumption = json.loads((CONFIG_DIR / "endpoint_sensitivity.json").read_text())
        raw = {
            a: pd.read_csv(FUTURES_UNDERLYING_DIR / f"{a}.csv", index_col=0, parse_dates=True)
            for a in assumption["instruments"]
        }
        returns, changes = apply_endpoint_assumption(returns, raw, assumption)
        changes.to_csv(out / "endpoint_changes.csv", index=False)
        (out / "assumption.json").write_text(json.dumps(assumption, indent=2) + "\n")
    returns.to_csv(out / "returns_used.csv", float_format="%.17g")
    meta = pd.read_csv(ASSET_MAP_PATH).set_index("ID")
    sample = returns.loc[base["start"] : base["end"]]
    eligible = eligibility(returns, meta, base, settings)
    audit = audit_data(returns, source, known, schedule, eligible, base, settings, out)
    audit.update(
        data_scenario="conditional_endpoint_assumption"
        if endpoint_sensitivity
        else "preserved_policy",
        assumed_return_additions=len(changes) if endpoint_sensitivity else 0,
        endpoint_assumption_verified=False if endpoint_sensitivity else None,
    )
    (out / "sample_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    missing = eligible.loc[sample.index] & sample.isna()
    pd.DataFrame(
        [
            {"month": str(month), "instrument": asset}
            for (month, asset), flag in missing.stack().items()
            if flag
        ],
        columns=["month", "instrument"],
    ).to_csv(out / "missing_eligible_returns.csv", index=False)
    if not endpoint_sensitivity:
        endpoint_candidates(out)
    classes, counts, class_stats = class_portfolios(returns, eligible, meta, sample.index)
    classes.to_csv(out / "class_returns.csv")
    counts.assign(total=counts.sum(axis=1)).to_csv(out / "eligible_counts.csv")
    eligible.loc[sample.index].to_csv(out / "eligible_instruments.csv")
    class_stats.to_csv(out / "class_statistics.csv", index=False)
    autocorr = rank_autocorrelation(classes)
    autocorr.to_csv(out / "autocorrelation.csv", index=False)
    targets, covariance, diagnostics = build_forecasts(returns, meta, base, settings)
    diagnostics.to_csv(out / "correlated_target_diagnostics.csv", index=False)
    for strategy, target in targets.items():
        target.to_csv(out / f"correlated_{strategy}_targets.csv")
    metrics, alphas, ledgers, details, gross, failures = evaluate(
        sample,
        source.loc[sample.index],
        known.loc[sample.index],
        targets,
        covariance,
        settings,
        out,
    )
    if failures:
        if endpoint_sensitivity:
            (out / "run_status.json").write_text(
                json.dumps({"status": "blocked", "failures": failures}, indent=2) + "\n"
            )
            raise ValueError(
                "Endpoint sensitivity still has missing held returns; see its run_status.json"
            )
        make_charts(classes, counts, autocorr, {}, settings, out)
        primary_failures = [f for f in failures if f["band"] == 0.1 and f["cost_bps"] == 5]
        write_blocked_report(class_stats, autocorr, audit, primary_failures or failures)
        write_manifest(settings, base, original_hashes, out)
        (out / "run_status.json").write_text(
            json.dumps(
                {
                    "status": "blocked_missing_held_returns",
                    "full_period_comparison_published": False,
                    "sample": audit,
                    "failures": failures,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "DATA BLOCKER: preserved-policy comparison withheld; docs/DATA_STATUS.md refreshed.",
            flush=True,
        )
        return 2
    metrics.to_csv(out / "comparison.csv", index=False)
    alphas.to_csv(out / "alpha.csv", index=False)
    pd.DataFrame({name: ledger.net_return for name, ledger in ledgers.items()}).to_csv(
        out / "monthly_returns.csv"
    )
    attribution = {}
    for strategy in ["trend", "static"]:
        name = key(settings["primary_band"], settings["primary_cost_bps"], strategy)
        net, exposure, risk, summary = class_attribution(
            ledgers[name], gross[name], details[name], covariance, meta
        )
        for suffix, frame in [
            ("class_net_contributions", net),
            ("class_exposure", exposure),
            ("class_forecast_risk", risk),
            ("executed", details[name]["exposure"]),
            ("instrument_costs", details[name]["cost"]),
            ("gross_attribution", gross[name]),
        ]:
            frame.to_csv(out / f"correlated_{strategy}_{suffix}.csv")
        summary.to_csv(out / f"{strategy}_class_attribution.csv", index=False)
        attribution[strategy] = summary
    assert not metrics.gross_breaches.any() and not metrics.risk_breaches.any()
    stability = stability_summary(ledgers)
    stability.to_csv(out / "stability.csv", index=False)
    make_charts(classes, counts, autocorr, ledgers, settings, out)
    write_report(
        metrics,
        alphas,
        class_stats,
        autocorr,
        attribution,
        audit,
        settings,
        base,
        out,
        report_path,
        assumption,
        stability,
    )
    write_manifest(settings, base, original_hashes, out)
    (out / "run_status.json").write_text(
        json.dumps(
            {
                "status": "conditional_sensitivity_complete"
                if endpoint_sensitivity
                else "complete",
                "endpoint_assumption": assumption,
                "full_period_comparison_published": True,
                "sample": audit,
            },
            indent=2,
        )
        + "\n"
    )
    print(metrics[(metrics.band == 0.1) & (metrics.cost_bps == 5)].to_string(index=False))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-sensitivity", action="store_true")
    raise SystemExit(main(parser.parse_args().endpoint_sensitivity))
