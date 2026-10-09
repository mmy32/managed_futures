"""Validate inferred monthly endpoint rules; do not publish reconstructed returns.

Run: python scripts/review_endpoints.py
Outputs are audit evidence only. All source files remain unchanged.
"""

import hashlib
import json
from decimal import Decimal

import numpy as np
import pandas as pd

from src.config import FUTURES_UNDERLYING_DIR, MONTHLY_RETURNS_PATH, PROJECT_ROOT, QPS_OUTPUT_DIR
from src.data_loader import load_daily_prices, load_monthly_returns
from src.data_processing.endpoints import close_frames, endpoints

ROOT = PROJECT_ROOT
OUT = QPS_OUTPUT_DIR / "endpoint_review"
TOL = 5e-8


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(candidate, supplied):
    both = candidate.notna() & supplied.notna()
    diff = (candidate - supplied).abs()
    return {
        "matched_values": int((both & diff.le(TOL)).sum()),
        "mismatched_values": int((both & diff.gt(TOL)).sum()),
        "missing_observed": int((candidate.isna() & supplied.notna()).sum()),
        "extra_values": int((candidate.notna() & supplied.isna()).sum()),
        "matched_blanks": int((candidate.isna() & supplied.isna()).sum()),
        "max_abs_difference": float(diff.loc[both].max()) if both.any() else None,
    }


def save(frame, name):
    pd.DataFrame(frame).to_csv(OUT / f"{name}.csv", index=False, float_format="%.12g")


def boundary_checks():
    # Synthetic cases distinguish calendar age, weekends, terminal truncation,
    # and adjacent-month returns without skipping an invalid endpoint.
    m = pd.period_range("2024-03", "2024-04", freq="M")
    d = pd.DataFrame(
        {"Close": [100.0, 101.0, 105.0]},
        index=pd.to_datetime(["2024-03-26", "2024-03-27", "2024-04-30"]),
    )
    e = endpoints(d, m)
    assert e.loc[m[0], "target_date"] == pd.Timestamp("2024-03-29")
    assert e.loc[m[0], "age"] == 2
    d2 = d.drop(pd.Timestamp("2024-03-27"))
    assert endpoints(d2, m).loc[m[0], "endpoint_accepted"]
    d3 = pd.DataFrame({"Close": [100.0, 105.0]}, index=pd.to_datetime(["2024-03-25", "2024-04-30"]))
    assert not endpoints(d3, m).loc[m[0], "endpoint_accepted"]
    p = endpoints(d3, m).endpoint_close
    assert (p / p.shift(1) - 1).isna().all()
    terminal = pd.DataFrame(
        {"Close": [100.0, 101.0]}, index=pd.to_datetime(["2014-11-28", "2014-12-30"])
    )
    mm = pd.period_range("2014-11", "2014-12", freq="M")
    assert not endpoints(terminal, mm).iloc[-1].endpoint_accepted
    assert endpoints(terminal, mm, bound_span=False).iloc[-1].endpoint_accepted


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted((FUTURES_UNDERLYING_DIR).glob("*.csv"))
    source_paths = files + [
        MONTHLY_RETURNS_PATH,
        QPS_OUTPUT_DIR / "daily_audit/stale_runs.csv",
        QPS_OUTPUT_DIR / "daily_audit/calendar_gaps.csv",
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in source_paths}
    raw = close_frames(load_daily_prices())
    supplied = load_monthly_returns()
    # Loaders return floats; the stored decimal strings are kept as audit evidence.
    saved_tokens = pd.read_csv(MONTHLY_RETURNS_PATH, index_col=0, dtype=str)
    labels = supplied.index
    supplied.index = labels.to_period("M")
    saved_tokens.index = supplied.index
    months = supplied.index
    variants = [
        ("calendar_end_3d_bounded", "calendar", 3, True, "calendar"),
        ("weekday_end_1d_bounded", "weekday", 1, True, "calendar"),
        ("weekday_end_2d_bounded", "weekday", 2, True, "calendar"),
        ("weekday_end_3d_unbounded", "weekday", 3, False, "calendar"),
        ("weekday_end_3d_bounded", "weekday", 3, True, "calendar"),
        ("weekday_end_4d_bounded", "weekday", 4, True, "calendar"),
        ("weekday_end_3weekdays_bounded", "weekday", 3, True, "weekdays"),
        ("last_observed_bounded", "weekday", 999, True, "calendar"),
    ]
    variant_rows, instrument_rows = [], []
    selected_e, selected_r = {}, {}
    for name, anchor, lookback, bound, age_kind in variants:
        tables = {
            a: endpoints(d, months, anchor, lookback, bound, age_kind) for a, d in raw.items()
        }
        ratios = {a: e.endpoint_close / e.endpoint_close.shift(1) - 1 for a, e in tables.items()}
        # Diagnostic only: RL's own monthly return takes precedence, with ER
        # filling absent RL returns. Never ratio price levels across tickers.
        candidate = {a: ratios[a] for a in supplied}
        candidate["RL"] = ratios["RL"].combine_first(ratios["ER"])
        per_variant = []
        for asset in supplied:
            c = compare(candidate[asset], supplied[asset])
            instrument_rows.append(dict(rule=name, ID=asset, **c))
            per_variant.append(c)
        counts = {
            k: sum(row[k] for row in per_variant)
            for k in per_variant[0]
            if k != "max_abs_difference"
        }
        variant_rows.append(
            dict(
                rule=name,
                **counts,
                max_abs_difference=max(x["max_abs_difference"] or 0 for x in per_variant),
            )
        )
        if name == "weekday_end_3d_bounded":
            selected_e, selected_r = tables, ratios
            selected = candidate
    save(variant_rows, "rule_comparison")
    save(instrument_rows, "rule_comparison_by_instrument")
    picked = next(row for row in variant_rows if row["rule"] == "weekday_end_3d_bounded")
    assert picked["mismatched_values"] == picked["missing_observed"] == picked["extra_values"] == 0
    assert picked["matched_values"] == int(supplied.notna().sum().sum())

    evidence, blank_causes, continuation = [], [], []
    for asset in supplied:
        for i, month in enumerate(months):
            fallback = (
                asset == "RL"
                and pd.isna(selected_r["RL"].loc[month])
                and pd.notna(selected_r["ER"].loc[month])
            )
            source = "ER" if fallback else asset
            table = selected_e[source]
            current = table.loc[month]
            previous = table.loc[months[i - 1]] if i else None
            observed = supplied.loc[month, asset]
            token = saved_tokens.loc[month, asset]
            # Account for the source's mix of 9-decimal and 3-significant-digit
            # scientific notation, plus a small float arithmetic allowance.
            precision = (
                min(TOL, 0.5 * 10.0 ** Decimal(token).as_tuple().exponent) + 1e-12
                if pd.notna(token) and float(token) != 0
                else 1e-12
            )
            delta = float(selected[asset].loc[month] - observed) if pd.notna(observed) else np.nan
            if pd.notna(observed):
                assert abs(delta) <= precision, (asset, month, token, delta, precision)
            row = {
                "ID": asset,
                "month": str(month),
                "source_ID": source,
                "supplied_return": observed,
                "return_available": bool(pd.notna(selected[asset].loc[month])),
                "current_target": current.target_date,
                "current_price_date": current.price_date,
                "current_age_days": current.age,
                "current_accepted": bool(current.endpoint_accepted),
                "previous_target": previous.target_date if previous is not None else pd.NaT,
                "previous_price_date": previous.price_date if previous is not None else pd.NaT,
                "previous_age_days": previous.age if previous is not None else np.nan,
                "previous_accepted": bool(previous.endpoint_accepted)
                if previous is not None
                else False,
                "value_difference": delta,
                "supplied_token": token,
                "saved_precision_tolerance": precision if pd.notna(observed) else np.nan,
            }
            evidence.append(row)
            if fallback:
                continuation.append(row)
            if pd.isna(observed):
                first, last = (
                    supplied[asset].first_valid_index(),
                    supplied[asset].last_valid_index(),
                )
                if month < first:
                    kind = "leading_history_or_first_return"
                elif month > last:
                    kind = "target_beyond_raw_end"
                else:
                    kind = "endpoint_outside_3_calendar_days"
                blank_causes.append(
                    {
                        "ID": asset,
                        "month": str(month),
                        "category": kind,
                        "current_target": current.target_date,
                        "current_price_date": current.price_date,
                        "current_age_days": current.age,
                        "previous_price_date": previous.price_date
                        if previous is not None
                        else pd.NaT,
                        "previous_age_days": previous.age if previous is not None else np.nan,
                    }
                )
    save(evidence, "endpoint_evidence")
    save(blank_causes, "blank_classification")
    save(continuation, "rl_er_continuation_evidence")

    gaps = pd.read_csv(
        QPS_OUTPUT_DIR / "daily_audit/calendar_gaps.csv", parse_dates=["previous_date", "next_date"]
    )
    ss_evidence = []
    for row in gaps.loc[gaps.ID.eq("SS") & gaps.long_gap].itertuples(index=False):
        days = pd.bdate_range(
            row.previous_date + pd.Timedelta(days=1), row.next_date - pd.Timedelta(days=1)
        )
        for day in days:
            ss_evidence.append(
                {
                    "date": day,
                    "gap_start": row.previous_date,
                    "gap_end": row.next_date,
                    "SS_present": day in raw["SS"].index,
                    "GS_present": day in raw["GS"].index,
                    "LX_present": day in raw["LX"].index,
                }
            )
    save(ss_evidence, "ss_year_end_peer_evidence")
    absent = pd.bdate_range("2014-07-01", "2014-07-31").difference(raw["AP"].index)
    save(
        [
            {
                "ID": "AP",
                "date": day,
                "source_calendar_month": "2014-07",
                "raw_rows": len(raw["AP"].loc["2014-07"]),
                "exchange_report_trading_days": 23,
            }
            for day in absent
        ],
        "ap_missing_july_sessions",
    )

    stale = pd.read_csv(QPS_OUTPUT_DIR / "daily_audit/stale_runs.csv", parse_dates=["start", "end"])
    stale_evidence = []
    for row in stale.loc[stale.identical_ohlc].itertuples(index=False):
        table = selected_e[row.ID]
        affected = table.loc[table.endpoint_accepted & table.price_date.between(row.start, row.end)]
        affected_returns = set()
        for month in affected.index:
            for candidate_month in [month, month + 1]:
                if candidate_month in months and pd.notna(supplied.loc[candidate_month, row.ID]):
                    affected_returns.add(str(candidate_month))
        stale_evidence.append(
            {
                "ID": row.ID,
                "start": row.start,
                "end": row.end,
                "repeated_OHLC_observations": row.observations,
                "endpoint_months": ";".join(map(str, affected.index)),
                "affected_return_months": ";".join(sorted(affected_returns)),
                "assessment": "unverified_vendor_price_convention; do_not_edit",
            }
        )
    save(stale_evidence, "repeated_ohlc_endpoint_impact")
    boundary_checks()
    assert all(sha(ROOT / p) == h for p, h in hashes.items())
    save([{"path": p, "sha256": h} for p, h in hashes.items()], "source_manifest")
    summary = dict(
        **picked,
        cells=supplied.size,
        supplied_dates_are_last_weekday=bool(
            labels.equals(
                pd.DatetimeIndex(
                    [pd.offsets.BMonthEnd().rollback(t) for t in months.to_timestamp("M")]
                )
            )
        ),
        RL_fallback_months=len(continuation),
        RL_fallback_start=continuation[0]["month"],
        RL_fallback_end=continuation[-1]["month"],
        blank_categories=pd.DataFrame(blank_causes).category.value_counts().to_dict(),
        source_files_unchanged=True,
        boundary_checks_passed=True,
        all_values_match_saved_csv_precision=True,
        match_tolerance_decimal=TOL,
        caveat="Agreement to stored CSV precision is not proof of original code or vendor data accuracy.",
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
