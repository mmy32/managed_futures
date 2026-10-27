"""Audit reported activity and run a conditional, matched-window collateral sensitivity."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from run_band_experiment import digest, load_inputs

from src.backtest.engine import simulate
from src.backtest.implementation_diagnostics import (
    activity_summary,
    collateral_rates,
    lagged_activity,
    map_trade_sources,
)
from src.backtest.performance import performance
from src.backtest.qps_baseline import portfolio_limits
from src.backtest.qps_v2 import build_forecasts_v2, load_rules
from src.config import CONFIG_DIR, PROJECT_ROOT, RAW_DATA_DIR
from src.data_loader.daily_prices import load_daily_bars
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost


def audit_activity(months, meta, spec, out):
    summaries, panels = [], []
    for market, frame in load_daily_bars().items():
        summaries.append(
            dict(
                source_series=market, **activity_summary(frame, spec["repeat_screen_observations"])
            )
        )
        panel = lagged_activity(
            frame,
            months,
            spec["volume_lookback_observations"],
            spec["volume_information_lag_bars"],
            spec["stale_after_calendar_days"],
        )
        panels.append(panel.reset_index().assign(source_series=market))
    summary = pd.DataFrame(summaries)
    summary["asset_class"] = summary.source_series.map(meta.AssetClass)
    summary.to_csv(out / "daily_activity_audit.csv", index=False)
    activity = pd.concat(panels, ignore_index=True)
    activity["month"] = activity.month.astype(str)
    activity.to_csv(out / "lagged_activity.csv.gz", index=False, compression="gzip")
    return activity


def coverage_row(group):
    passed = group.positive_recent_volume_screen
    return dict(
        events=len(group),
        event_coverage=float(passed.mean()),
        notional_coverage=float(group.loc[passed, "notional_nav"].sum() / group.notional_nav.sum()),
        incomplete=int((~group.complete_nonnegative_window).sum()),
        zero_mean_volume=int(group.mean_reported_volume.eq(0).sum()),
        stale=int(group.stale.sum()),
    )


def audit_trades(reference, source, activity, meta, out):
    for name, expected in json.loads((reference / "ARTIFACT_SHA256.json").read_text()).items():
        if digest(reference / name) != expected:
            raise ValueError(f"Step 4 artifact changed: {name}")
    summaries = []
    for strategy in ["trend", "static"]:
        name = f"trade_only_trade2bps_roll0bps_{strategy}_events.csv.gz"
        events = pd.read_csv(reference / "output" / name)
        selected = map_trade_sources(events, source)
        joined = selected.merge(
            activity,
            on=["month", "source_series"],
            how="left",
            validate="many_to_one",
            indicator=True,
        )
        if not joined._merge.eq("both").all():
            raise ValueError("Missing source-specific activity audit")
        joined["asset_class"] = joined.market.map(meta.AssetClass)
        joined.drop(columns="_merge").to_csv(
            out / f"{strategy}_trade_activity.csv.gz", index=False, compression="gzip"
        )
        groups = [("ALL", joined), *joined.groupby("asset_class")]
        for label, group in groups:
            summaries.append(dict(strategy=strategy, asset_class=label, **coverage_row(group)))
    pd.DataFrame(summaries).to_csv(out / "trade_activity_coverage.csv", index=False)


def funding_case(sample, source, known, targets, covariance, settings, rates, case, out):
    bps, strategy, funded = case
    name = f"trade{bps}bps_{strategy}_{'rf' if funded else 'zero_cash'}"
    details = {}
    ledger, _ = simulate(
        sample,
        targets[strategy].loc[sample.index],
        LinearBpsCost(bps),
        source,
        position_policy=BandPolicy(
            covariance, portfolio_limits(settings), settings["primary_band"]
        ),
        source_known_at=known,
        risk_free=rates if funded else None,
        instrument_details=details,
    )
    expected = rates * (1 - ledger.rebalance_cost) if funded else 0
    np.testing.assert_allclose(ledger.collateral_income, expected, atol=1e-12)
    np.testing.assert_allclose(
        ledger.net_return, ledger.gross_return + ledger.collateral_income - ledger.cost, atol=1e-12
    )
    assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
    metrics = performance(ledger, risk_free=rates)
    metrics["excess_sharpe_vs_workbook_rf"] = metrics.pop("sharpe")
    ledger.to_csv(out / f"{name}_ledger.csv")
    details["exposure"].to_csv(out / f"{name}_exposure.csv.gz", compression="gzip")
    print("Completed", name, flush=True)
    return dict(
        run=name,
        trade_bps=bps,
        strategy=strategy,
        collateral_rf=funded,
        **metrics,
        collateral_income_ann=ledger.collateral_income.mean() * 12,
        gross_mean_ann=ledger.gross_return.mean() * 12,
    )


def run_funding(returns, source, known, meta, spec, settings, base, out):
    targets, covariance, _ = build_forecasts_v2(returns, meta, base, settings, load_rules())
    sample = returns.loc[spec["funding_start"] : spec["funding_end"]]
    months = pd.period_range(spec["funding_start"], spec["funding_end"], freq="M")
    if not sample.index.equals(months):
        raise ValueError("Incomplete matched funding window")
    rates = collateral_rates(pd.read_excel(RAW_DATA_DIR / "Lecture3_livedata.xlsx"), months)
    rates.to_csv(out / "monthly_collateral_proxy.csv")
    rows = []
    for bps in spec["trade_costs_bps"]:
        for strategy in ["trend", "static"]:
            for funded in [False, True]:
                rows.append(
                    funding_case(
                        sample,
                        source.loc[months],
                        known.loc[months],
                        targets,
                        covariance,
                        settings,
                        rates,
                        (bps, strategy, funded),
                        out,
                    )
                )
    pd.DataFrame(rows).to_csv(out / "funding_comparison.csv", index=False)


def write_gate(out):
    gate = dict(
        supported=[
            "lagged reported-series activity diagnostics",
            "conditional fully collateralized RF sensitivity",
        ],
        unsupported={
            "capacity_and_participation": [
                "AUM",
                "dated delivery-contract IDs",
                "multipliers and quote units",
                "FX conversion",
                "verified contract volume",
            ],
            "market_impact": [
                "spreads",
                "execution horizon",
                "fills/benchmarks",
                "futures-specific coefficient calibration",
            ],
            "margin_and_borrowing": [
                "contract margin schedules",
                "cash balances",
                "cash buffers",
                "actual collateral yield and financing terms",
            ],
        },
        adopted_strategy_change=False,
    )
    (out / "data_gate.json").write_text(json.dumps(gate, indent=2) + "\n")


def main(reference, roll_reference, out):
    if out.exists():
        raise ValueError("Use a new output directory to preserve earlier results")
    spec = json.loads((CONFIG_DIR / "implementation_feasibility.json").read_text())
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    base = json.loads((PROJECT_ROOT / settings["base_config"]).read_text())
    assert settings["primary_band"] == spec["band"]
    returns, source, known, meta, hashes = load_inputs(reference)
    out.mkdir(parents=True)
    activity = audit_activity(returns.loc[base["start"] : base["end"]].index, meta, spec, out)
    audit_trades(roll_reference, source, activity, meta, out)
    run_funding(returns, source, known, meta, spec, settings, base, out)
    write_gate(out)
    (out / "assumptions.json").write_text(json.dumps(spec, indent=2) + "\n")
    (out / "raw_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    assert all(digest(PROJECT_ROOT / path) == expected for path, expected in hashes.items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--roll-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.reference.resolve(), args.roll_reference.resolve(), args.output.resolve())
