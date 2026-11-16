"""Audit original supplied daily/monthly arithmetic; never construct trading inputs or score returns."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from construct_returns import assemble

from src.config import PROJECT_ROOT, RAW_DATA_DIR
from src.data_loader import (
    load_daily_bars,
    load_daily_prices,
    load_monthly_return_tokens,
    load_monthly_returns,
)
from src.data_processing.endpoints import close_frames

REFERENCE = PROJECT_ROOT / "reports/pc_experiment_20261105/freeze.json"
AUDIT_NOTICE = (
    "Historical arithmetic audit only. historical_span_endpoints uses full-file date spans, "
    "and the reconstructed RL/ER fallback uses the current month's availability. These "
    "retrospective conventions reproduce the supplied file; they are NOT trading inputs, "
    "an out-of-sample assessment, or verified executable futures P&L."
)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stored_tolerance(token):
    """Original reconciliation rule: half the final CSV digit, capped, plus numerical slack."""
    number = Decimal(token)
    return (min(5e-8, 0.5 * 10.0 ** number.as_tuple().exponent) if number else 0.0) + 1e-12


def reconcile_returns(supplied, reproduced, tokens):
    """Compare arithmetic and every blank without filling or dropping any observation."""
    if not (supplied.index.equals(reproduced.index) and supplied.columns.equals(reproduced.columns)
            and supplied.index.equals(tokens.index) and supplied.columns.equals(tokens.columns)):
        raise ValueError("Monthly returns, reconstruction and stored tokens must have identical axes")
    rows, violations = [], []
    for market in supplied:
        before, after = supplied[market], reproduced[market]
        mask_mismatch = before.isna() ^ after.isna()
        observed = before.notna() & after.notna()
        tolerances = tokens.loc[observed, market].map(stored_tolerance)
        difference = (after.loc[observed] - before.loc[observed]).abs()
        value_mismatch = difference.gt(tolerances)
        rows.append({
            "market": market, "supplied_observed": int(before.notna().sum()),
            "reproduced_observed": int(after.notna().sum()), "supplied_missing": int(before.isna().sum()),
            "reproduced_missing": int(after.isna().sum()),
            "missingness_mismatches": int(mask_mismatch.sum()),
            "value_mismatches": int(value_mismatch.sum()),
            "max_abs_difference": float(difference.max()) if len(difference) else None,
            "matching_missingness": not mask_mismatch.any(),
            "all_observed_within_stored_precision": not value_mismatch.any(),
        })
        for month in before.index[mask_mismatch]:
            violations.append({"month": str(month), "market": market,
                               "issue": "missingness_mismatch", "supplied": before.loc[month],
                               "reproduced": after.loc[month], "tolerance": None})
        for month in value_mismatch.index[value_mismatch]:
            violations.append({"month": str(month), "market": market,
                               "issue": "value_outside_stored_precision", "supplied": before.loc[month],
                               "reproduced": after.loc[month], "tolerance": tolerances.loc[month]})
    return pd.DataFrame(rows), pd.DataFrame(violations, columns=[
        "month", "market", "issue", "supplied", "reproduced", "tolerance"
    ])


def ohlc_review_flags(bars):
    """Flag field inconsistencies for vendor review without editing data or failing the audit."""
    rows = []
    for market, frame in bars.items():
        reasons = {
            "high_below_low": frame.High.lt(frame.Low),
            "open_outside_high_low": frame.Open.lt(frame.Low) | frame.Open.gt(frame.High),
            "close_outside_high_low": frame.Close.lt(frame.Low) | frame.Close.gt(frame.High),
            "negative_volume": frame.Volume.lt(0),
            "negative_open_interest": frame.OpenInterest.lt(0),
        }
        for reason, affected in reasons.items():
            for date in frame.index[affected]:
                rows.append({"market": market, "date": str(date.date()), "flag": reason,
                             **frame.loc[date].to_dict(), "treatment": "review_only_no_changes"})
    return pd.DataFrame(rows, columns=["market", "date", "flag", "Open", "High", "Low", "Close",
                                       "Volume", "OpenInterest", "treatment"])


def _load_inputs(raw_dir):
    directory = raw_dir / "futures_underlying"
    frozen = json.loads(REFERENCE.read_text())["raw_inputs"]
    expected = {Path(name).name for name in frozen if "/futures_underlying/" in name}
    actual = {path.name for path in directory.glob("*.csv")}
    if actual != expected:
        raise ValueError(f"Original daily-file universe mismatch: missing={sorted(expected - actual)}, "
                         f"extra={sorted(actual - expected)}")
    files = {f"futures_underlying/{name}": directory / name for name in sorted(actual)}
    files["MonthlyReturns.csv"] = raw_dir / "MonthlyReturns.csv"
    hashes = {name: _digest(path) for name, path in files.items()}
    matches = {name: value == frozen[f"data/raw/{name}"] for name, value in hashes.items()}
    bars, prices = load_daily_bars(directory), load_daily_prices(directory, iso_dates=True)
    supplied = load_monthly_returns(files["MonthlyReturns.csv"])
    tokens = load_monthly_return_tokens(files["MonthlyReturns.csv"])
    supplied.index = supplied.index.to_period("M")
    tokens.index = supplied.index
    if (not supplied.index.is_unique or not supplied.index.equals(
            pd.period_range(supplied.index[0], supplied.index[-1], freq="M"))):
        raise ValueError("Supplied monthly file must have a complete, unique monthly calendar")
    values = supplied.to_numpy()
    if not np.isfinite(values[~np.isnan(values)]).all():
        raise ValueError("Observed monthly returns must be finite")
    required = set(supplied.columns) | {"ER"}
    if not required <= set(prices.columns):
        raise ValueError(f"Missing reconstruction sources: {sorted(required - set(prices.columns))}")
    return files, hashes, matches, bars, prices, supplied, tokens


def _summary_text(summary):
    rows = ["# Original supplied-data verification", "", AUDIT_NOTICE, "",
            f"**Status: {summary['status']}**", "",
            (f"Checked {summary['daily_files']} daily files and "
            f"{summary['observed_daily_closes']:,} observed positive, finite closes, spanning "
            f"{summary['daily_start']} through {summary['daily_end']}."), "",
            (f"The supplied monthly panel contains {summary['monthly_months']} months and "
            f"{summary['monthly_markets']} markets. Its full calendar and all missing cells "
            "were retained during reconstruction."), "",
            (f"Missing-state mismatches: **{summary['missingness_mismatches']}**. "
            f"Observed values outside stored precision: **{summary['value_mismatches']}**. "
            f"Maximum absolute difference: {summary['max_abs_difference']:.3g}."), "",
            ("Tolerance is min(5e-8, half the final stored CSV digit) + 1e-12; "
            "stored zero uses 1e-12. No unknown return is replaced by zero."), "",
            (f"Vendor review flags: **{summary['review_flags']}**. Flags do not alter data "
            "or certify field meaning. See [OHLC review flags](ohlc_review_flags.csv)."), "",
            ("All original-input identities and unchanged bytes are recorded in "
            "[input hashes](input_hashes.csv); [checks](checks.csv) and "
            "[per-market reconciliation](reconciliation.csv) provide the detailed results."), "",
            ("These daily inputs end in 2014. This audit does not provide post-2014 daily "
            "data, select an evaluation period, fit a strategy or compute performance.")]
    return "\n".join(rows) + "\n"


def _write_results(output, loaded):
    files, hashes, matches, bars, prices, supplied, tokens = loaded
    reproduced, _, _ = assemble(close_frames(prices), supplied.index, supplied.columns,
                                historical_reproduction=True)
    reconciliation, violations = reconcile_returns(supplied, reproduced, tokens)
    flags = ohlc_review_flags(bars)
    unchanged = {name: _digest(path) == hashes[name] for name, path in files.items()}
    checks = pd.DataFrame([
        {"check": "strict_daily_and_monthly_schema", "passed": True},
        {"check": "original_frozen_input_hashes", "passed": all(matches.values())},
        {"check": "all_missing_states_reproduced", "passed": reconciliation.matching_missingness.all()},
        {"check": "all_observed_values_within_stored_precision",
         "passed": reconciliation.all_observed_within_stored_precision.all()},
        {"check": "original_bytes_unchanged", "passed": all(unchanged.values())},
    ])
    summary = {
        "status": "passed" if checks.passed.all() else "failed", "scope": AUDIT_NOTICE,
        "daily_files": len(bars), "observed_daily_closes": int(prices.notna().sum().sum()),
        "daily_start": str(prices.index[0].date()), "daily_end": str(prices.index[-1].date()),
        "monthly_months": len(supplied), "monthly_markets": len(supplied.columns),
        "missingness_mismatches": int(reconciliation.missingness_mismatches.sum()),
        "value_mismatches": int(reconciliation.value_mismatches.sum()),
        "max_abs_difference": float(reconciliation.max_abs_difference.max()),
        "review_flags": len(flags), "strategy_scored": False,
    }
    for name, frame in [("reconciliation", reconciliation), ("violations", violations),
                        ("ohlc_review_flags", flags), ("checks", checks)]:
        frame.to_csv(output / f"{name}.csv", index=False)
    pd.DataFrame([{"path": name, "sha256": value, "matches_original": matches[name],
                   "bytes_unchanged": unchanged[name]} for name, value in hashes.items()]).to_csv(
        output / "input_hashes.csv", index=False)
    (output / "status.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    (output / "SUMMARY.md").write_text(_summary_text(summary))
    return 0 if summary["status"] == "passed" else 1


def audit_original_inputs(raw_dir, output):
    """Write a new immutable original-file audit; preserve all inputs and earlier reports."""
    raw_dir, output = Path(raw_dir).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new output directory; earlier verification records are not overwritten")
    output.mkdir(parents=True)
    try:
        return _write_results(output, _load_inputs(raw_dir))
    except (OSError, ValueError, TypeError, KeyError) as error:
        status = {"status": "failed", "scope": AUDIT_NOTICE, "error": str(error), "strategy_scored": False}
        (output / "status.json").write_text(json.dumps(status, indent=2) + "\n")
        pd.DataFrame([{"check": "input_structure_or_arithmetic", "passed": False,
                       "error": str(error)}]).to_csv(output / "checks.csv", index=False)
        (output / "SUMMARY.md").write_text(
            f"# Original supplied-data verification\n\n**Status: failed**\n\n{error}\n\n{AUDIT_NOTICE}\n"
        )
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DATA_DIR)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    status = audit_original_inputs(args.raw_dir, args.output)
    print(f"Original-input verification {'passed' if status == 0 else 'failed'}: {args.output}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
