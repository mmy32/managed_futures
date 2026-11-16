"""Run professor-supplied monthly data; export conditional results and strict checks."""

import argparse
import hashlib
import importlib.metadata
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.backtest.monthly_report import write_readable_report
from src.backtest.monthly_runner import (
    export_comparison,
    read_monthly,
    strict_checks,
    verify_exported_accounting,
)
from src.config import PROJECT_ROOT
from src.data_loader import load_asset_map, load_full_sample_returns
from src.data_processing.monthly_sample import COVERAGE_SELECTION_NOTE, audit_monthly_universe


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def configuration(path):
    spec = json.loads(path.read_text())
    base = json.loads((PROJECT_ROOT / spec["base_config"]).read_text())
    risk = json.loads((PROJECT_ROOT / spec["risk_config"]).read_text())
    base.update({key: spec[key] for key in ("start", "end", "information_lag_months")})
    risk.update({key: spec[key] for key in ("volatility_months", "volatility_floor_annual",
                                          "gross_cap", "portfolio_risk_ceiling",
                                          "correlation_shrinkage")})
    risk.update(primary_band=spec["trading_band"], primary_cost_bps=spec["cost_bps"])
    if spec["sample_policy"] != "coverage_conditioned_and_strict_check":
        raise ValueError("This runner requires both conditional results and strict checks")
    if spec["cash_interest"] != "zero":
        raise ValueError("Only the declared zero cash-interest convention is supported")
    start, split, end = (pd.Period(spec[key], "M")
                         for key in ("start", "development_end", "end"))
    if not start <= split < end:
        raise ValueError("Monthly periods must satisfy start <= development_end < end")
    if type(spec["information_lag_months"]) is not int or spec["information_lag_months"] < 1:
        raise ValueError("Monthly information lag must be a positive integer")
    # These resolved settings describe the monthly run, not the separate daily candidate.
    risk["risk_model"] = {"type": "monthly_dcc_garch", "rescale": spec["rescale"],
                          "correlation_shrinkage": spec["correlation_shrinkage"]}
    risk["risk_model_note"] = (
        "Monthly GARCH/DCC estimated from supplied monthly returns; one-month covariance "
        "annualized by 12. Expanding annual fits use prior December; the rolling comparator "
        "uses the same shrinkage and past-only eligibility. See monthly run specification."
    )
    return spec, base, risk


def fingerprints(config_path, spec):
    raw = [PROJECT_ROOT / spec[key] for key in ("monthly_returns", "asset_map")]
    inputs = [*raw, config_path, PROJECT_ROOT / spec["base_config"],
              PROJECT_ROOT / spec["risk_config"]]
    source = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    source += sorted((PROJECT_ROOT / "tests").rglob("*.py"))
    source += [Path(__file__).resolve(), PROJECT_ROOT / "pyproject.toml"]
    return {
        "inputs": {_input_name(path): digest(path) for path in inputs},
        "source": {str(path.relative_to(PROJECT_ROOT)): digest(path) for path in source},
    }


def _input_name(path):
    path = path.resolve()
    return str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)


def verify_fingerprints(record):
    for name, expected in record["inputs"].items():
        path = Path(name)
        if digest(path if path.is_absolute() else PROJECT_ROOT / path) != expected:
            raise ValueError(f"Monthly run input changed: {name}")
    for name, expected in record["source"].items():
        if digest(PROJECT_ROOT / name) != expected:
            raise ValueError(f"Monthly implementation changed: {name}")


def load_inputs(spec, base):
    returns = load_full_sample_returns(PROJECT_ROOT / spec["monthly_returns"], units="decimal")
    if str(returns.index[-1]) != spec["end"] or pd.Period(base["start"], "M") not in returns.index:
        raise ValueError("Workbook coverage does not match the declared monthly sample")
    meta = load_asset_map(PROJECT_ROOT / spec["asset_map"]).reindex(returns.columns)
    if meta.AssetClass.isna().any():
        raise ValueError("Every monthly market requires an asset class")
    audit = audit_monthly_universe(returns, base["exclude_from_strategy"], spec["end"],
                                   development_end=spec["development_end"])
    return returns, meta, audit


def export_inputs(output, meta, audit, spec, base, risk, record):
    selected = audit.index[audit.included_coverage]
    audit.to_csv(output / "universe_audit.csv")
    meta.to_csv(output / "asset_metadata.csv")
    write_json(output / "resolved_config.json", {"spec": spec, "base": base, "risk": risk})
    write_json(output / "run_declaration.json", {
        **record, "created_utc": datetime.now(UTC).isoformat(),
        "scope_note": COVERAGE_SELECTION_NOTE,
        "selected_markets": list(selected), "selection_independent_of_return_values": True,
        "independent_preregistration": False,
        "versions": {name: importlib.metadata.version(name)
                     for name in ("numpy", "pandas", "scipy", "statsmodels")},
    })
    with zipfile.ZipFile(output / "source_snapshot.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name in record["source"]:
            archive.write(PROJECT_ROOT / name, name)


def final_status(output, spec, audit, strict):
    first_active = {}
    for path in sorted(output.glob("*_ledger.csv.gz")):
        if path.name.endswith("_shadow_ledger.csv.gz"):
            continue
        ledger = read_monthly(path)
        active = ledger.index[ledger.held_instruments.gt(0)]
        first_active[path.name.removesuffix("_ledger.csv.gz")] = str(active[0]) if len(active) else None
    common = read_monthly(output / "common_eligibility.csv.gz")
    return {"status": "COMPLETED_CONDITIONAL_ON_COVERAGE", "scope_note": COVERAGE_SELECTION_NOTE,
                "new_strategy_backtest_performed": True, "independent_oos_proof": False,
                "workbook_markets": len(audit), "coverage_markets": int(audit.included_coverage.sum()),
                "predeclared_exclusions": int(audit.exclusion_reason.str.startswith("Predeclared").sum()),
                "strict_markets": int((~audit.exclusion_reason.str.startswith("Predeclared")).sum()),
                "start": spec["start"], "end": spec["end"], "development_end": spec["development_end"],
                "first_active_months": first_active,
                "common_eligible_at_start": int(common.loc[spec["start"]].sum()),
                "eligible_at_start": int(common.loc[spec["start"]].sum()),
                "strict_checks": strict}


def seal(output, record):
    verify_fingerprints(record)
    payload = {**record, "outputs": {
        str(path.relative_to(output)): digest(path) for path in sorted(output.rglob("*"))
        if path.is_file() and path.name not in ("manifest.json", "manifest.sha256")
    }}
    write_json(output / "manifest.json", payload)
    (output / "manifest.sha256").write_text(digest(output / "manifest.json") + "\n")


def run(config_path, output):
    if output.exists():
        raise ValueError("Use a new output directory; earlier results must be preserved")
    spec, base, risk = configuration(config_path)
    record = fingerprints(config_path, spec)
    returns, meta, audit = load_inputs(spec, base)
    output.mkdir(parents=True)
    write_json(output / "status.json", {"status": "RUNNING", "complete_results_published": False})
    try:
        export_inputs(output, meta, audit, spec, base, risk, record)
        retained = [name for name in returns if name not in base["exclude_from_strategy"]]
        strict = strict_checks(returns[retained], meta.loc[retained], base, risk, spec)
        write_json(output / "strict_checks.json", strict)
        selected = list(audit.index[audit.included_coverage])
        metrics = export_comparison(returns[selected], meta.loc[selected], base, risk, spec, output)
        metrics.to_csv(output / "metrics.csv", index=False, float_format="%.17g")
        checks = verify_exported_accounting(output, spec)
        checks.append({"check": "input_and_source_fingerprints", "status": "PASS",
                           "detail": "Immutable raw files and source bytes match the run declaration"})
        verify_fingerprints(record)
        pd.DataFrame(checks).to_csv(output / "checks.csv", index=False)
        write_json(output / "status.json", final_status(output, spec, audit, strict))
        write_readable_report(output)
        seal(output, record)
    except Exception as error:
        write_json(output / "status.json", {"status": "FAILED", "complete_results_published": False,
                                            "error": str(error)})
        raise
    print(metrics[["period", "risk_model", "portfolio", "sharpe", "vol_ann", "mean_ann"]].to_string(index=False))
    print(f"Readable results: {output / 'SUMMARY.html'}")


def verify_existing(output):
    if digest(output / "manifest.json") != (output / "manifest.sha256").read_text().strip():
        raise ValueError("Monthly result manifest changed")
    record = json.loads((output / "manifest.json").read_text())
    verify_fingerprints(record)
    for name, expected in record["outputs"].items():
        if digest(output / name) != expected:
            raise ValueError(f"Monthly result changed: {name}")
    spec = json.loads((output / "resolved_config.json").read_text())["spec"]
    checks = verify_exported_accounting(output, spec)
    print(f"PASS: {len(checks)} portfolio accounts, period metrics, all input/source/output hashes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify-existing", type=Path)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/monthly_full_sample.json")
    args = parser.parse_args()
    if args.verify_existing:
        verify_existing(args.verify_existing.resolve())
    else:
        run(args.config.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
