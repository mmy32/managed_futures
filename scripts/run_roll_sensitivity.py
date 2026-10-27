"""Data-gated, explicitly hypothetical roll calendars for v2 and matching STATIC."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
from run_band_experiment import load_inputs, read_panel

from src.backtest.attribution import class_attribution
from src.backtest.engine import simulate
from src.backtest.performance import performance
from src.backtest.qps_baseline import portfolio_limits
from src.backtest.qps_v2 import build_forecasts_v2, load_rules
from src.backtest.roll_events import execution_journal
from src.backtest.sample_diagnostics import risk_diagnostics
from src.config import CONFIG_DIR, PROJECT_ROOT, RAW_DATA_DIR
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost
from src.transaction_cost_model.rolls import RollSchedule


def audit_data(meta, out):
    rows = []
    for path in sorted((RAW_DATA_DIR / "futures_underlying").glob("*.csv")):
        frame = pd.read_csv(path)
        rows.append(
            dict(
                market=path.stem,
                rows=len(frame),
                first_date=frame.iloc[0, 0],
                last_date=frame.iloc[-1, 0],
                fields=",".join(frame.columns),
                underlying_map_available=path.stem in meta.index,
                contract_id_available=False,
                expiry_available=False,
                roll_date_available=False,
                multiplier_available=False,
                adjustment_method_available=False,
            )
        )
        if list(frame.columns[1:]) != ["Open", "High", "Low", "Close", "Volume", "OpenInterest"]:
            raise ValueError(f"Unexpected daily schema: inspect {path}")
    pd.DataFrame(rows).to_csv(out / "contract_data_audit.csv", index=False)
    book = openpyxl.load_workbook(
        RAW_DATA_DIR / "Lecture3_livedata.xlsx", read_only=True, data_only=True
    )
    sheets = {
        s.title: list(next(s.iter_rows(min_row=1, max_row=1, values_only=True))) for s in book
    }
    book.close()
    result = dict(
        daily_series=len(rows),
        asset_map_fields=[meta.index.name, *meta.columns],
        workbook_fields=sheets,
        actual_roll_history_supported=False,
        assumption_sensitivity_supported=True,
        missing=[
            "dated delivery-contract identities",
            "expiry/actual roll schedules",
            "contract multipliers and quote units",
            "dated currency conversion conventions",
            "vendor continuous-price adjustment lineage",
            "execution cost coverage in supplied returns",
        ],
        interpretation="Underlying IDs and currencies are available, but not a dated contract chain. Repository endpoint notes describe already-rolled inputs without a verified adjustment method. OHLC/volume/OI do not establish roll dates.",
    )
    (out / "data_gate.json").write_text(json.dumps(result, indent=2) + "\n")


def normalize_ledger(ledger):
    if "roll_cost" not in ledger:
        ledger = ledger.assign(
            roll_cost=0.0,
            ordinary_cost=ledger.cost,
            rolled_notional=0.0,
            roll_turnover=0.0,
            ordinary_turnover=ledger.turnover,
        )
    np.testing.assert_allclose(ledger.ordinary_cost + ledger.roll_cost, ledger.cost, atol=1e-12)
    np.testing.assert_allclose(
        ledger.ordinary_turnover + ledger.roll_turnover, ledger.turnover, atol=1e-12
    )
    assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
    return ledger


def class_summary(ledger, gross, details, covariance, meta):
    _, _, _, summary = class_attribution(ledger, gross, details, covariance, meta)
    labels = meta.AssetClass.reindex(gross.columns)
    total = details["cost"]
    roll = details.get("roll_cost", total * 0)
    values = (
        pd.DataFrame(
            {
                "gross_mean_ann": gross.T.groupby(labels).sum().T.mean() * 12,
                "ordinary_cost_ann": (total - roll).T.groupby(labels).sum().T.mean() * 12,
                "roll_cost_ann": roll.T.groupby(labels).sum().T.mean() * 12,
            }
        )
        .rename_axis("asset_class")
        .reset_index()
    )
    summary = summary.merge(values, on="asset_class", validate="one_to_one")
    np.testing.assert_allclose(
        summary.gross_mean_ann - summary.ordinary_cost_ann - summary.roll_cost_ann,
        summary.net_mean_ann,
        atol=1e-12,
    )
    return summary


def run_one(sample, source, known, targets, covariance, meta, settings, case, out):
    calendar, trade_bps, roll_bps, strategy, months = case
    name = f"{calendar}_trade{trade_bps}bps_roll{roll_bps}bps_{strategy}"
    schedule = None
    if months:
        flags = np.repeat(np.isin(sample.index.month, months)[:, None], len(sample.columns), axis=1)
        due = pd.DataFrame(flags, index=sample.index, columns=sample.columns)
        assumed_known = pd.Series(
            sample.index[0].start_time - pd.Timedelta(days=1), index=sample.index
        )
        schedule = RollSchedule(due, assumed_known, roll_bps, "complete_roll")
    details = {}
    policy = BandPolicy(covariance, portfolio_limits(settings), settings["primary_band"])
    ledger, gross = simulate(
        sample,
        targets[strategy],
        LinearBpsCost(trade_bps),
        source,
        position_policy=policy,
        source_known_at=known,
        instrument_details=details,
        roll_schedule=schedule,
    )
    ledger = normalize_ledger(ledger)
    events = execution_journal(sample, source, ledger, details, trade_bps, roll_bps)
    ledger.to_csv(out / f"{name}_ledger.csv")
    events.to_csv(out / f"{name}_events.csv.gz", index=False, compression="gzip")
    details["exposure"].to_csv(out / f"{name}_exposure.csv.gz", compression="gzip")
    classes = class_summary(ledger, gross, details, covariance, meta)
    classes.to_csv(out / f"{name}_classes.csv", index=False)
    metadata = dict(
        run=name,
        calendar=calendar,
        trade_bps=trade_bps,
        roll_bps=roll_bps,
        strategy=strategy,
        assumed_rolls_per_year=len(months),
    )
    row = dict(
        **metadata,
        **performance(ledger),
        **risk_diagnostics(ledger)[1],
        gross_mean_ann=ledger.gross_return.mean() * 12,
        ordinary_cost_ann=ledger.ordinary_cost.mean() * 12,
        roll_cost_ann=ledger.roll_cost.mean() * 12,
        ordinary_turnover_ann=ledger.ordinary_turnover.mean() * 12,
        roll_turnover_ann=ledger.roll_turnover.mean() * 12,
        rolled_notional_ann=ledger.rolled_notional.mean() * 12,
        gross_breaches=int(ledger.gross_limit_breach.sum()),
        risk_breaches=int(ledger.risk_limit_breach.sum()),
    )
    print("Completed", name, flush=True)
    return row, classes.assign(**metadata), ledger


def scenarios(specification):
    for trade in specification["trade_costs_bps"]:
        for strategy in ["trend", "static"]:
            yield "trade_only", trade, 0, strategy, []
        for calendar, months in specification["calendars"].items():
            for roll in specification["roll_costs_bps"]:
                for strategy in ["trend", "static"]:
                    yield calendar, trade, roll, strategy, months


def check_reference(ledger, case, reference):
    calendar, trade, _, strategy, _ = case
    if calendar != "trade_only":
        return None
    name = f"correlated_band10_{trade}bps_{strategy}_ledger.csv"
    old = read_panel(reference / "output/endpoint_sensitivity_v2" / name)
    pd.testing.assert_frame_equal(
        ledger[old.columns], old, check_exact=False, rtol=1e-10, atol=1e-12
    )
    difference = np.max(
        np.abs(ledger[old.columns].to_numpy(dtype=float) - old.to_numpy(dtype=float))
    )
    return dict(file=name, maximum_absolute_difference=float(difference))


def run_cases(data, targets, covariance, settings, specification, reference, out):
    sample, source, known, meta = data
    summaries, classes, checks = [], [], []
    for case in scenarios(specification):
        summary, attribution, ledger = run_one(
            sample, source, known, targets, covariance, meta, settings, case, out
        )
        summaries.append(summary)
        classes.append(attribution)
        check = check_reference(ledger, case, reference)
        if check is not None:
            checks.append(check)
    pd.DataFrame(summaries).to_csv(out / "comparison.csv", index=False)
    pd.concat(classes, ignore_index=True).to_csv(out / "class_comparison.csv", index=False)
    assert len(summaries) == 36 and len(checks) == 4
    (out / "validation.json").write_text(
        json.dumps(
            dict(
                runs=36,
                all_accounting_and_limits_passed=True,
                event_journals_reconciled=True,
                class_attribution_reconciled=True,
                trade_only_reference_checks=checks,
            ),
            indent=2,
        )
        + "\n"
    )


def main(reference, out):
    if out.exists():
        raise ValueError("Use a new output directory to preserve earlier results")
    specification = json.loads((CONFIG_DIR / "roll_sensitivity.json").read_text())
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    base = json.loads((PROJECT_ROOT / settings["base_config"]).read_text())
    assert settings["primary_band"] == specification["band"]
    returns, source, known, meta, hashes = load_inputs(reference)
    out.mkdir(parents=True)
    audit_data(meta, out)
    (out / "assumptions.json").write_text(json.dumps(specification, indent=2) + "\n")
    (out / "raw_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    targets, covariance, _ = build_forecasts_v2(returns, meta, base, settings, load_rules())
    sample = returns.loc[base["start"] : base["end"]]
    data = sample, source.loc[sample.index], known.loc[sample.index], meta
    run_cases(data, targets, covariance, settings, specification, reference, out)
    assert all(
        hashlib.sha256((PROJECT_ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items()
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.reference.resolve(), args.output.resolve())
