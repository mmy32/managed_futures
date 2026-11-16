"""Verify corrected DCC-GARCH integration on original daily prices through December 2014.

This is a historical risk-model diagnostic, not a strategy backtest or an OOS assessment.
Run from the project root with PYTHONPATH=. and choose a new output directory.
"""

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from src.backtest.oos_inputs import strategy_inputs
from src.backtest.qps_baseline import build_risk_model
from src.config import CONFIG_DIR, PROJECT_ROOT, RAW_DATA_DIR
from src.data_loader import load_asset_map, load_daily_prices, load_full_sample_returns
from src.models import MarketData
from src.risk_model.daily import daily_returns

HISTORICAL_END = pd.Period("2014-12", freq="M")
FORECAST_START = pd.Period("2014-01", freq="M")
REPLAY_CUTOFF = pd.Period("2014-02", freq="M")
FORECAST_MONTHS = pd.PeriodIndex(["2014-01", "2014-02", "2014-12"], freq="M")
SOURCE_FILES = [
    "scripts/verify_historical_garch.py", "src/risk_model/garch.py", "src/risk_model/daily.py",
    "src/backtest/qps_baseline.py", "src/backtest/oos_inputs.py",
    "src/data_processing/strategy_inputs.py", "src/data_processing/endpoints.py",
    "src/data_loader/daily_prices.py", "src/data_loader/full_sample.py",
    "src/data_loader/asset_map.py", "config/baseline_config.json", "config/risk_config.json",
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": detail}


def input_inventory(raw):
    frozen = json.loads((PROJECT_ROOT / "reports/pc_experiment_20261105/freeze.json")
                        .read_text())["raw_inputs"]
    daily = sorted((Path(name).name, expected) for name, expected in frozen.items()
                   if "/futures_underlying/" in name)
    records = []
    for name, expected in daily:
        path = raw / "futures_underlying" / name
        actual = digest(path)
        records.append({"path": str(path.resolve()), "file": name, "sha256": actual,
                        "archived_sha256": expected, "matches_archived": actual == expected})
    for name in ("AssetMapCsv.csv", "MonthlyReturns_FullSample.xlsx"):
        path = raw / name
        records.append({"path": str(path.resolve()), "file": name, "sha256": digest(path),
                        "archived_sha256": "", "matches_archived": None})
    return pd.DataFrame(records), [Path(name).stem for name, _ in daily]


def prepare(prices, supplied_monthly, base, risk, end):
    monthly, source, known, daily = strategy_inputs(
        prices, list(supplied_monthly), risk, end, base["exclude_from_strategy"]
    )
    # Preserve every supplied historical monthly cell except the independently selected RL
    # source. The full-sample workbook's retrospective fallback is not a trading schedule.
    returns = supplied_monthly.loc[:end].copy()
    returns["RL"] = monthly.RL.reindex(returns.index)
    return returns, source, known, daily


def unknown_return_mask(prices, source, daily):
    quote = prices.reindex(daily.index)
    unknown = quote.isna() | quote.shift(1).isna()
    if "RL" in daily:
        use_er = source.RL.reindex(daily.index.to_period("M")).eq("ER").to_numpy()
        unknown["RL"] = np.where(use_er, unknown.ER, unknown.RL)
    return unknown[daily.columns]


def source_and_gap_checks(output, prices, source, daily):
    unknown = unknown_return_mask(prices, source, daily)
    details = pd.DataFrame({
        "market": daily.columns,
        "unknown_quote_intervals": unknown.sum().to_numpy(),
        "nonmissing_returns_on_unknown_intervals": (unknown & daily.notna()).sum().to_numpy(),
        "zeros_on_unknown_intervals": (unknown & daily.eq(0)).sum().to_numpy(),
        "observed_zero_returns": daily.eq(0).sum().to_numpy(),
        "observed_daily_returns": daily.notna().sum().to_numpy(),
    })
    details.to_csv(output / "daily_gap_audit.csv", index=False)
    last_rl = prices.RL.last_valid_index()
    chosen = source.RL.reindex(daily.index.to_period("M"))
    dates = daily.index[(daily.index > last_rl) & chosen.eq("ER").to_numpy()]
    raw_returns = daily_returns(prices.reindex(daily.index)[["RL", "ER"]])
    continuation = pd.DataFrame({
        "selected_RL_risk_return": daily.loc[dates, "RL"],
        "ER_own_daily_return": raw_returns.loc[dates, "ER"],
        "unavailable_raw_RL_return": raw_returns.loc[dates, "RL"],
    })
    continuation.to_csv(output / "RL_ER_continuation.csv", index_label="date")
    retained = list(daily)
    perturbed = prices.copy()
    excluded = list(set(prices)-set(retained)-{"ER"})
    perturbed.loc[:, excluded] *= 17
    perturbed.loc[pd.Timestamp("2013-06-15"), excluded] = 1e6
    from src.data_processing.strategy_inputs import source_consistent_daily_returns

    replay = source_consistent_daily_returns(perturbed.sort_index(), source, retained)
    return [
        check("Unavailable daily quotes remain unknown", int((unknown & daily.notna()).sum().sum()) == 0,
              f"{int(unknown.sum().sum()):,} unavailable quote intervals inspected; "
              "none was assigned an observed or zero return."),
        check("ER supplies risk returns after original RL terminates",
              len(dates) > 0 and continuation.unavailable_raw_RL_return.isna().all()
              and np.allclose(continuation.selected_RL_risk_return,
                              continuation.ER_own_daily_return, equal_nan=True),
              f"RL's last quote is {last_rl.date()}; "
              f"{int(continuation.selected_RL_risk_return.notna().sum()):,} subsequent ER risk returns retained."),
        check("Excluded/unused markets and their extra dates cannot change risk returns",
              daily.equals(replay), "Perturbed excluded/unused price levels and an excluded-only "
              "Saturday; the complete retained risk-return panel is identical."),
    ], last_rl


def model_for(daily, meta, base, risk, lag):
    effective = {**base, "information_lag_months": lag,
                 "risk_forecast_start": str(FORECAST_START)}
    return build_risk_model(effective, risk, meta, daily=daily)


def forecast(model, returns, meta):
    data = MarketData(returns, meta)
    vol = model.volatility(data)
    eligible = vol.loc[FORECAST_START:].gt(0)
    covariance, details = model.covariances(data, eligible)
    return covariance, eligible, details


def largest_difference(original, other, cutoff):
    return max(float(np.max(np.abs(matrix-other[month])))
               for month, matrix in original.items() if month <= cutoff)


def actual_model_checks(output, prices, supplied, meta, base, risk):
    returns, source, _, daily = prepare(prices, supplied, base, risk, HISTORICAL_END)
    returns.to_csv(output / "monthly_eligibility_inputs.csv", index_label="month")
    rows, last_rl = source_and_gap_checks(output, prices, source, daily)
    print("Fitting actual 2014 DCC-GARCH and forecasting the declared historical months...", flush=True)
    model = model_for(daily, meta, base, risk, lag=1)
    baseline, eligible, _ = forecast(model, returns, meta)
    print("Fitting the prior annual model for January's lag-2 information sensitivity...", flush=True)
    delayed = model.variant(lag=2)
    delayed_covariance, delayed_eligible, _ = forecast(delayed, returns, meta)
    fitted = model.fitted_parameters()
    fitted.to_csv(output / "fitted_parameters.csv", index_label="fit_year")
    success = [name for name in fitted if name.endswith("_success")]
    rows.append(check("Actual pooled GARCH and DCC annual fits converge",
                      bool(success) and fitted[success].all().all(),
                      f"{len(fitted)} fitted annual models; diagnostics include optimizer objectives, "
                      "iteration counts and elapsed fitting time."))
    excluded = set(base["exclude_from_strategy"])
    rows.append(check("EC and YM are excluded before parameter estimation",
                      not (set(model.daily) & excluded)
                      and all(not (set(year.params) & excluded) for year in model._years.values()),
                      f"{len(model.daily.columns)} retained estimation series; excluded markets absent "
                      "from every fitted annual parameter set."))
    comparisons = [("future mutation", HISTORICAL_END), ("truncated history", REPLAY_CUTOFF)]
    for name, end in comparisons:
        altered = prices.loc[:end.end_time].copy()
        if name == "future mutation":
            altered.loc[REPLAY_CUTOFF.start_time:, ["AP", "ER"]] *= [2.0, 0.4]
            altered.loc["2014-02-03":"2014-02-07", "AP"] = np.nan
        changed_returns, _, _, changed_daily = prepare(altered, supplied, base, risk, end)
        print(f"Independently refitting the actual 2014 model: {name}...", flush=True)
        independent = model_for(changed_daily, meta, base, risk, lag=1)
        changed_covariance, _, _ = forecast(independent, changed_returns, meta)
        error = largest_difference(baseline, changed_covariance, REPLAY_CUTOFF)
        rows.append(check(f"Actual lag-1 {name} preserves earlier forecasts", error < 1e-12,
                          f"Independent estimation/filtering; maximum covariance difference "
                          f"through {REPLAY_CUTOFF}: {error:.3g}."))
    summary, matrices = [], []
    for lag, covariance, active in [(1, baseline, eligible), (2, delayed_covariance, delayed_eligible)]:
        for month in FORECAST_MONTHS:
            ids = np.flatnonzero(active.loc[month].to_numpy())
            block = covariance[month][np.ix_(ids, ids)]
            minimum = float(np.linalg.eigvalsh(block).min()) if len(ids) else np.nan
            sigma = np.sqrt(np.diag(block))
            summary.append({"information_lag": lag, "holding_month": str(month),
                            "information_through": str(month-lag), "eligible_markets": len(ids),
                            "minimum_eigenvalue": minimum,
                            "median_annual_volatility": float(np.median(sigma)),
                            "RL_annual_volatility": float(np.sqrt(covariance[month][
                                returns.columns.get_loc("RL"), returns.columns.get_loc("RL")]))})
            rows.append(check(f"Lag {lag}, {month}: active covariance is positive definite",
                              len(ids) > 0 and np.isfinite(block).all() and minimum > 0,
                              f"{len(ids)} eligible markets; minimum eigenvalue {minimum:.6g}."))
            for i, j in np.ndindex(covariance[month].shape):
                matrices.append({"information_lag": lag, "holding_month": str(month),
                                 "row_market": returns.columns[i], "column_market": returns.columns[j],
                                 "annual_covariance": covariance[month][i, j]})
    pd.DataFrame(summary).to_csv(output / "forecast_summary.csv", index=False)
    pd.DataFrame(matrices).to_csv(output / "forecast_covariances.csv", index=False)
    pd.concat([model.coverage_diagnostics().assign(information_lag=1),
               delayed.coverage_diagnostics().assign(information_lag=2)]).to_csv(
        output / "forecast_coverage.csv", index=False)
    return rows, {"daily_start": str(prices.index.min().date()),
                  "daily_end": str(prices.index.max().date()), "daily_rows": len(daily),
                  "retained_estimation_markets": len(daily.columns),
                  "last_original_RL_quote": str(last_rl.date()),
                  "historical_monthly_end": str(returns.index[-1]),
                  "historical_monthly_rows": len(returns), "fit_years": list(map(int, fitted.index)),
                  "fit_seconds": fitted.fit_seconds.to_dict()}


def write_report(output, checks, context):
    passed = bool(checks.passed.all())
    lines = ["# Historical DCC-GARCH integration verification", "",
             f"**{'PASS' if passed else 'FAIL'}: {int(checks.passed.sum())}/{len(checks)} checks passed.**", "",
             ("These calculations use the restored original daily futures prices, not synthetic "
              "observations. They verify risk-model estimation, missing-data handling, source "
              "consistency and causality on inspected historical data through December 2014. "
              "No strategy portfolio was scored and no post-2014 observation was fitted or evaluated."), "",
             ("The monthly workbook is explicitly loaded in decimal units and restricted through "
              "2014-12. Its RL column is replaced by the same prior-only source rule used by the "
              "strategy; all other supplied monthly observations and missing cells are preserved. "
              "No March 1997 or Hong Kong endpoint overlay is applied."), "",
             ("Forecasts use the configured 36-month eligibility window, 2% annual volatility floor "
              "and DCC shrinkage. These are covariance forecasts before portfolio-level shadow "
              "rescaling; the diagnostic does not simulate holdings, trades or performance."), "",
             (f"Runtime: {context['runtime_seconds']:.2f} seconds. "
             f"Original daily files matched: {context.get('original_daily_files_matched', 0)}/62."), "",
             "| Check | Result | Evidence |", "| --- | --- | --- |"]
    for row in checks.itertuples(index=False):
        detail = row.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row.check} | {'PASS' if row.passed else 'FAIL'} | {detail} |")
    if (output / "forecast_summary.csv").is_file():
        summary = pd.read_csv(output / "forecast_summary.csv")
        lines += ["", "## Declared historical forecast dates", "",
                  "| Lag | Holding month | Information through | Eligible markets | Median annual volatility | RL annual volatility |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in summary.itertuples(index=False):
            lines.append(f"| {row.information_lag} | {row.holding_month} | {row.information_through} "
                         f"| {row.eligible_markets} | {row.median_annual_volatility:.2%} "
                         f"| {row.RL_annual_volatility:.2%} |")
    lines += ["", "## Inspect or reproduce", "",
              "- `input_inventory.csv`: all input hashes and daily-file identity checks.",
              "- `fitted_parameters.csv`: actual annual estimates, convergence and timing.",
              ("- `daily_gap_audit.csv` and `RL_ER_continuation.csv`: unknown intervals remain "
              "unknown; the selected source supplies its own returns."),
              ("- `forecast_covariances.csv`, `forecast_summary.csv`, `forecast_coverage.csv`: "
              "forecast values and observed/missing daily history counts."),
              "- `monthly_eligibility_inputs.csv`: the historical monthly input panel actually used.", "",
              ("Missing-observation Gaussian conditional moments and the 21-day covariance "
               "forecast remain modeling approximations. Passing these historical integration "
               "checks does not validate vendor vintages, executable fills, every historical "
               "month, strategy performance, or an independent out-of-sample advantage."), "",
              "Choose a new directory to rerun from the project root:", "", "```sh",
              "PYTHONPATH=. .venv/bin/python scripts/verify_historical_garch.py --output reports/historical_garch_new",
              "```", ""]
    (output / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def run_verification(output, raw=RAW_DATA_DIR):
    output, raw = Path(output), Path(raw)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    source_hashes = {name: digest(PROJECT_ROOT / name) for name in SOURCE_FILES}
    rows, context, inventory = [], {}, pd.DataFrame()
    try:
        inventory, daily_markets = input_inventory(raw)
        inventory.to_csv(output / "input_inventory.csv", index=False)
        matched = int(inventory.matches_archived.eq(True).sum())
        context["original_daily_files_matched"] = matched
        rows.append(check("Original daily inputs match the frozen reference", matched == 62,
                          f"{matched}/62 original daily CSV hashes match; no raw input is modified."))
        if matched != 62:
            raise ValueError("Historical verification requires all 62 original daily files")
        base = json.loads((CONFIG_DIR / "baseline_config.json").read_text())
        risk = json.loads((CONFIG_DIR / "risk_config.json").read_text())
        supplied = load_full_sample_returns(raw / "MonthlyReturns_FullSample.xlsx",
                                            units="decimal").loc[:HISTORICAL_END]
        prices = load_daily_prices(raw / "futures_underlying", daily_markets).loc[:HISTORICAL_END.end_time]
        meta = load_asset_map(raw / "AssetMapCsv.csv").reindex(supplied.columns)
        records, actual_context = actual_model_checks(output, prices, supplied, meta, base, risk)
        rows.extend(records)
        context.update(actual_context)
    except (ValueError, KeyError, IndexError, TypeError, RuntimeError, OSError) as error:
        rows.append(check("Historical integration completed", False, f"{type(error).__name__}: {error}"))
    input_hashes = dict(zip(inventory.path, inventory.sha256, strict=True)) if len(inventory) else {}
    unchanged = all(Path(path).is_file() and digest(path) == expected
                    for path, expected in input_hashes.items())
    unchanged &= source_hashes == {name: digest(PROJECT_ROOT / name) for name in SOURCE_FILES}
    rows.append(check("Input and implementation hashes remain unchanged", unchanged,
                      "Input files are immutable; hashes are checked before and after the calculations."))
    table = pd.DataFrame(rows)
    table.to_csv(output / "checks.csv", index=False)
    context.update(runtime_seconds=perf_counter()-started, passed=bool(table.passed.all()),
                   independent_oos_assessment_performed=False, strategy_performance_computed=False)
    write_report(output, table, context)
    (output / "summary.json").write_text(json.dumps(context, indent=2)+"\n", encoding="utf-8")
    manifest = {
        "created_utc": datetime.now(UTC).isoformat(), "passed": context["passed"],
        "data_source": "Original daily futures prices; supplied monthly eligibility data through 2014-12 only",
        "inputs": input_hashes, "source_sha256": source_hashes,
        "versions": {"python": platform.python_version(), **{
            package: version(package) for package in ("numpy", "pandas", "scipy")}},
        "artifact_sha256": {path.name: digest(path) for path in sorted(output.iterdir()) if path.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return context["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; never overwritten")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DATA_DIR)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output exists: {args.output}; choose a new directory")
    passed = run_verification(args.output, args.raw_dir)
    print(f"{'PASS' if passed else 'FAIL'}: {args.output / 'SUMMARY.md'}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
