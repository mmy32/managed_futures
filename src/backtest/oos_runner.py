"""Prepare and run the declared inverse-volatility versus HRP evaluation."""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.engine import simulate
from src.backtest.hrp_comparison import comparison_components, load_comparison
from src.backtest.oos_inputs import input_paths, load_bundle, strategy_inputs, validate_declaration
from src.backtest.performance import performance
from src.backtest.qps_baseline import forecasts_from
from src.config import PROJECT_ROOT
from src.portfolio_construction import BandPolicy
from src.risk_model import standardized_returns
from src.transaction_cost_model import LinearBpsCost


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    """Fingerprint implementation and configuration, including uncommitted changes."""
    files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    files += sorted((PROJECT_ROOT / "config").glob("*.json"))
    files.append(PROJECT_ROOT / "scripts/run_hrp_oos.py")
    files.append(PROJECT_ROOT / "pyproject.toml")
    return {str(path.relative_to(PROJECT_ROOT)): digest(path) for path in files}


def environment_versions():
    return {"python": platform.python_version(), **{
        name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scipy", "statsmodels")
    }}


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _git_head():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _hash_inputs(files):
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise ValueError(f"Missing prepared input files: {missing}")
    return {name: {"path": str(path), "sha256": digest(path)} for name, path in files.items()}


def prepare(declaration_path, price_dir, asset_map_path, output):
    """Validate inputs and write an immutable preparation record; do not score returns."""
    declaration_path, output = Path(declaration_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new preparation directory; existing records are never overwritten")
    declaration_bytes = declaration_path.read_bytes()
    declaration = json.loads(declaration_bytes)
    declaration_hash = hashlib.sha256(declaration_bytes).hexdigest()
    spec, base, risk = load_comparison()
    validate_declaration(declaration, base, risk)
    _, files = input_paths(price_dir, asset_map_path, declaration["universe"])
    before = _hash_inputs(files)
    code = source_hashes()
    _, _, loaded_files, coverage = load_bundle(price_dir, asset_map_path, declaration, base, risk)
    if (_hash_inputs(loaded_files) != before or source_hashes() != code
            or digest(declaration_path) != declaration_hash
            or load_comparison() != (spec, base, risk)):
        raise ValueError("Inputs or code changed while preparing the evaluation")
    record = {
        "schema_version": 1,
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "status": "prepared_not_evaluated",
        "preparation_note": "Local timestamp records preparation; it is not independent proof of preregistration.",
        "declaration": declaration,
        "declaration_sha256": declaration_hash,
        "comparison": spec,
        "base": base,
        "risk": risk,
        "price_dir": str(Path(price_dir).resolve()),
        "asset_map": str(Path(asset_map_path).resolve()),
        "input_files": before,
        "coverage": coverage,
        "source_sha256": code,
        "git_head": _git_head(),
        "versions": environment_versions(),
    }
    output.mkdir(parents=True)
    snapshot = output / "source_snapshot.zip"
    with zipfile.ZipFile(snapshot, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, expected in code.items():
            content = (PROJECT_ROOT / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"Source changed while creating the preparation snapshot: {name}")
            archive.writestr(name, content)
    with zipfile.ZipFile(snapshot) as archive:
        if set(archive.namelist()) != set(code) or any(
            hashlib.sha256(archive.read(name)).hexdigest() != expected
            for name, expected in code.items()
        ):
            raise ValueError("Prepared source snapshot failed verification")
    if (source_hashes() != code or _hash_inputs(files) != before
            or digest(declaration_path) != declaration_hash):
        raise ValueError("Inputs or source changed while creating the preparation snapshot")
    record["source_snapshot_sha256"] = digest(snapshot)
    _write_json(output / "preparation.json", record)
    (output / "preparation.sha256").write_text(digest(output / "preparation.json") + "\n")
    return record


def verify_preparation(prepared):
    """Reject changed inputs, code, or preparation records before or after a run."""
    prepared = Path(prepared).resolve()
    record_path = prepared / "preparation.json"
    if digest(record_path) != (prepared / "preparation.sha256").read_text().strip():
        raise ValueError("Preparation record changed")
    record = json.loads(record_path.read_text())
    if record.get("schema_version") != 1 or record.get("status") != "prepared_not_evaluated":
        raise ValueError("Invalid or already evaluated preparation record")
    if digest(prepared / "source_snapshot.zip") != record["source_snapshot_sha256"]:
        raise ValueError("Prepared source snapshot changed")
    if source_hashes() != record["source_sha256"]:
        raise ValueError("Source or configuration changed after preparation")
    if environment_versions() != record["versions"]:
        raise ValueError("Python or dependency versions changed after preparation")
    files = {name: Path(info["path"]) for name, info in record["input_files"].items()}
    if _hash_inputs(files) != record["input_files"]:
        raise ValueError("Input files changed after preparation")
    spec, base, risk = load_comparison()
    if (spec, base, risk) != (record["comparison"], record["base"], record["risk"]):
        raise ValueError("Comparison settings changed after preparation")
    validate_declaration(record["declaration"], base, risk)
    return record


def _shadow_readiness(parts, shared, risk, returns, meta, source, known, start, lag):
    """Require enough past, nonflat shadow observations to initialize the risk rescale."""
    base_model = parts.risk_model.model
    shadow = replace(parts, risk_model=base_model)
    shadow_base = {**shared, "end": str(start - 1)}
    targets, covariance, _ = forecasts_from(shadow, returns, meta, shadow_base)
    sample = returns.loc[shadow_base["start"] : shadow_base["end"]]
    ledger, _ = simulate(
        sample, targets["trend"], LinearBpsCost(risk["primary_cost_bps"]),
        source.loc[sample.index], source_known_at=known.loc[sample.index],
        position_policy=BandPolicy(covariance, shadow.limits, risk["primary_band"]),
        liquidate=False,
    )
    rescale = risk["risk_model"]["rescale"]
    observations = standardized_returns(ledger).loc[: start - lag].tail(rescale["window"])
    if len(observations) < rescale["minimum"]:
        raise ValueError(
            f"Insufficient valid pre-evaluation shadow observations at lag {lag}: "
            f"{len(observations)} < {rescale['minimum']}"
        )
    return len(observations)


def _comparison(record):
    declaration, spec, base, risk = (
        record["declaration"], record["comparison"], record["base"], record["risk"]
    )
    start, end, shadow = validate_declaration(declaration, base, risk)
    prices, meta, files, _ = load_bundle(
        record["price_dir"], record["asset_map"], declaration, base, risk
    )
    if _hash_inputs(files) != record["input_files"]:
        raise ValueError("Resolved input files changed after preparation")
    returns, source, known, daily = strategy_inputs(prices, declaration["universe"], risk, end)
    sample = returns.loc[start:end]
    if not sample.index.equals(pd.period_range(start, end, freq="M")):
        raise ValueError("Evaluation must have a complete and ordered monthly calendar")
    rows, cases, forecasts, readiness = [], {}, {}, {}
    for lag in declaration["information_lags_months"]:
        print(f"Information lag {lag}: preparing shared risk forecasts", flush=True)
        period_base = {**base, "start": str(shadow), "end": str(end),
                       "information_lag_months": lag, "risk_forecast_start": str(shadow)}
        shared, components = comparison_components(
            spec, period_base, risk, returns, meta, source, known, daily
        )
        readiness[str(lag)] = _shadow_readiness(
            components["baseline"], shared, risk, returns, meta, source, known, start, lag
        )
        for name, parts in components.items():
            target, covariance, diagnostics = forecasts_from(parts, returns, meta, shared)
            first = diagnostics[(diagnostics.month == start) & (diagnostics.strategy == "trend")]
            if len(first) != 1 or first.eligible.iloc[0] < base["minimum_instruments"]:
                raise ValueError(f"Insufficient eligible instruments at evaluation start for lag {lag}")
            details = {}
            ledger, _ = simulate(
                sample, target["trend"].loc[start:end], LinearBpsCost(risk["primary_cost_bps"]),
                source.loc[sample.index], source_known_at=known.loc[sample.index],
                position_policy=BandPolicy(covariance, parts.limits, risk["primary_band"]),
                instrument_details=details, liquidate=declaration["liquidate_at_end"],
            )
            if not ledger.index.equals(sample.index):
                raise ValueError("Portfolio ledger does not match the declared evaluation calendar")
            np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost, atol=1e-12)
            np.testing.assert_allclose(ledger.cost, ledger.turnover * risk["primary_cost_bps"] / 10000,
                                       atol=1e-12)
            if ledger.gross_limit_breach.any() or ledger.risk_limit_breach.any():
                raise ValueError(f"Executed portfolio breaches limits: lag {lag}, {name}")
            summary = performance(ledger)
            if not all(np.isfinite(summary[field]) for field in
                       ("mean_ann", "vol_ann", "zero_rate_mean_vol_ratio", "max_drawdown")):
                raise ValueError(f"Insufficient variation for performance metrics: lag {lag}, {name}")
            rows.append({"information_lag_months": lag, "portfolio": name, **summary})
            cases[(lag, name)] = (ledger, target["trend"].loc[start:end], details["exposure"])
            forecasts[(lag, name)] = diagnostics[
                diagnostics.month.between(start, end) & (diagnostics.strategy == "trend")
            ]
            print(f"Completed lag {lag}: {name}", flush=True)
    return pd.DataFrame(rows), cases, forecasts, readiness, returns, source, known


def _summary(metrics, cases, record, readiness):
    declaration = record["declaration"]
    lines = [
        "# Baseline and HRP evaluation", "",
        f"Evaluation: {declaration['evaluation_start']}–{declaration['evaluation_end']}; "
        f"{declaration['ordinary_cost_bps']} bps ordinary trading costs and "
        f"{declaration['trading_band']:.0%} trading bands.",
        "Both portfolios start flat; the final month includes liquidation. Cash income is zero.",
        "The return/volatility ratio uses a zero rate. Execution is an idealized prior-endpoint "
        "proxy; lag two is not a next-session fill.", "",
        "Data provenance and prior access have not been independently verified by this runner.", "",
        "| Information lag | Portfolio | Annual net mean | Volatility | Zero-rate ratio | Max drawdown | Annual turnover |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics.itertuples(index=False):
        lines.append(
            f"| {row.information_lag_months} | {row.portfolio} | {row.mean_ann:.2%} | "
            f"{row.vol_ann:.2%} | {row.zero_rate_mean_vol_ratio:.3f} | "
            f"{row.max_drawdown:.2%} | {row.turnover_ann:.2f}× |"
        )
    lines += ["", "Annualized paired mean differences, HRP minus baseline (bps of NAV/year):", "",
              "| Information lag | Gross change | Cost savings | Net change |",
              "| --- | ---: | ---: | ---: |"]
    for lag in declaration["information_lags_months"]:
        baseline, enhanced = cases[lag, "baseline"][0], cases[lag, "enhanced"][0]
        gross = (enhanced.gross_return - baseline.gross_return).mean() * 12 * 10000
        saving = (baseline.cost - enhanced.cost).mean() * 12 * 10000
        net = (enhanced.net_return - baseline.net_return).mean() * 12 * 10000
        np.testing.assert_allclose(net, gross + saving, rtol=0, atol=1e-9)
        lines.append(f"| {lag} | {gross:+.2f} | {saving:+.2f} | {net:+.2f} |")
    lines += ["", "These are arithmetic mean differences, not differences in CAGR.",
              "Lag 1 is primary; lag 2 is the declared information-delay sensitivity.",
              f"Pre-evaluation nonflat shadow observations: {readiness}.",
              "Data provenance is declared in `preparation.json`; the preparation timestamp "
              "does not independently certify preregistration or point-in-time vendor history."]
    return "\n".join(lines) + "\n"


def run(prepared):
    """Run the locked comparison, publishing results only after all four cases pass."""
    prepared = Path(prepared).resolve()
    record = verify_preparation(prepared)
    assessment = prepared / "assessment"
    if assessment.exists():
        raise ValueError("Assessment already exists; prepare a new record rather than overwrite it")
    assessment.mkdir()
    status_path = assessment / "status.json"
    _write_json(status_path, {"status": "running", "complete_results_published": False})
    try:
        metrics, cases, forecasts, readiness, returns, source, known = _comparison(record)
        verify_preparation(prepared)
        staging = assessment / "staging"
        staging.mkdir()
        metrics.to_csv(staging / "metrics.csv", index=False)
        returns.to_csv(staging / "strategy_returns.csv.gz")
        source.to_csv(staging / "strategy_source.csv.gz")
        known.to_csv(staging / "source_known_at.csv")
        for (lag, name), (ledger, target, exposure) in cases.items():
            ledger.to_csv(staging / f"lag{lag}_{name}_ledger.csv.gz")
            target.to_csv(staging / f"lag{lag}_{name}_target.csv.gz")
            exposure.to_csv(staging / f"lag{lag}_{name}_exposure.csv.gz")
            forecasts[lag, name].to_csv(staging / f"lag{lag}_{name}_diagnostics.csv", index=False)
        for lag in record["declaration"]["information_lags_months"]:
            baseline, enhanced = cases[lag, "baseline"][0], cases[lag, "enhanced"][0]
            paired = pd.DataFrame({"baseline_net": baseline.net_return,
                                   "enhanced_net": enhanced.net_return})
            paired["enhanced_minus_baseline"] = paired.enhanced_net - paired.baseline_net
            paired.to_csv(staging / f"lag{lag}_paired_returns.csv")
        (staging / "SUMMARY.md").write_text(_summary(metrics, cases, record, readiness))
        output_hashes = {p.name: digest(p) for p in sorted(staging.iterdir()) if p.is_file()}
        _write_json(staging / "output_sha256.json", output_hashes)
        verify_preparation(prepared)
        staging.rename(assessment / "results")
        _write_json(status_path, {
            "status": "complete", "complete_results_published": True,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "shadow_observations": readiness,
        })
    except Exception as error:
        published = assessment / "results"
        if published.exists() and not (assessment / "staging").exists():
            published.rename(assessment / "staging")
        _write_json(status_path, {"status": "failed", "complete_results_published": False,
                                  "error": str(error)})
        raise
    return assessment / "results"
