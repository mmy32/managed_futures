"""Read-only source audit. Run with python scripts/audit_daily.py.

Writes diagnostics to output/daily_audit; never cleans or replaces source data.
Weekdays are a screening calendar, not verified exchange trading sessions.
Close ratios are diagnostics of supplied price series, not certified futures P&L.
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/daily_audit"
FIELDS = ["Open", "High", "Low", "Close", "Volume", "OpenInterest"]
ABS_MOVE = 0.10
ROBUST_Z = 10
MIN_STALE_OBS = 4
MATCH_TOL = 5e-8  # absolute decimal return, well below one basis point


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(rows, name):
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(OUT / f"{name}.csv", index=False, float_format="%.12g")
    return frame


def weekday_gap(a, b):
    """Weekdays strictly between successive observations; includes holidays."""
    return pd.bdate_range(a + pd.Timedelta(days=1), b - pd.Timedelta(days=1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted((ROOT / "data/FuturesUnderlyingData").glob("*.csv"))
    source_paths = paths + [ROOT / "data/MonthlyReturns.csv", ROOT / "data/AssetMapCsv.csv"]
    before = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    returns = pd.read_csv(ROOT / "data/MonthlyReturns.csv", index_col=0)
    returns.index = pd.to_datetime(returns.index).to_period("M")
    meta = pd.read_csv(ROOT / "data/AssetMapCsv.csv").set_index("ID")
    # Audit the original supplied returns independently of corrected EDA outputs.
    mad = returns.sub(returns.median()).abs().median().replace(0, np.nan)
    monthly_z = returns.sub(returns.median()).div(1.4826 * mad)
    flags = (returns.abs() > .30) | (monthly_z.abs() > 6)
    flagged = returns.where(flags).stack().dropna().rename("return")
    flagged.index.names = ["month", "ID"]
    flagged = flagged.reset_index()
    flagged["month"] = flagged.month.astype(str)
    flagged.to_csv(OUT / "original_monthly_flags.csv", index=False)
    expected = {(str(month), asset) for month, asset in flags.stack().loc[lambda x: x].index}
    assert expected == set(zip(flagged.month, flagged.ID))
    missing = returns.isna() & returns.notna().cummax() & returns.notna().iloc[::-1].cummax().iloc[::-1]
    internal = missing.stack().loc[lambda x: x].rename("missing")
    internal.index.names = ["month", "ID"]
    internal = internal.reset_index()
    internal["month"] = internal.month.astype(str)
    internal.to_csv(OUT / "original_internal_gaps.csv", index=False)
    assert {(str(m), a) for m, a in missing.stack().loc[lambda x: x].index} == set(zip(internal.month, internal.ID))

    data, moves, endpoints = {}, {}, {}
    inventories, issues, extremes, gaps, stale = [], [], [], [], []
    missing_weekdays = []
    for path in paths:
        asset = path.stem
        d = pd.read_csv(path, index_col=0)
        assert list(d.columns) == FIELDS, path
        d.index = pd.to_datetime(d.index, errors="raise")
        assert d.index.is_unique and d.index.is_monotonic_increasing, path
        d = d.apply(pd.to_numeric, errors="raise")
        assert d.notna().all().all() and np.isfinite(d.to_numpy()).all(), path
        data[asset] = d
        close = d.Close
        r = close.pct_change(fill_method=None)
        moves[asset] = r
        median = r.median()
        mad_r = (r - median).abs().median()
        z = (r - median) / (1.4826 * mad_r) if mad_r else r * np.nan
        invalid = ((d.High < d.Low) | (d.High < d[["Open", "Close"]].max(axis=1)) |
                   (d.Low > d[["Open", "Close"]].min(axis=1)))
        negative_activity = d.Volume.lt(0) | d.OpenInterest.lt(0)
        nonpositive = d[["Open", "High", "Low", "Close"]].le(0).any(axis=1)
        for date in d.index[invalid | negative_activity | nonpositive]:
            issues.append(dict(ID=asset, date=date, **d.loc[date].to_dict(),
                               ohlc_inconsistent=bool(invalid.loc[date]),
                               negative_activity=bool(negative_activity.loc[date]),
                               nonpositive_price=bool(nonpositive.loc[date])))
        is_extreme = r.abs().ge(ABS_MOVE) | z.abs().ge(ROBUST_Z)
        for date in d.index[is_extreme]:
            i = d.index.get_loc(date)
            prev = d.index[i - 1]
            next_date = d.index[i + 1] if i + 1 < len(d) else pd.NaT
            next_r = r.iloc[i + 1] if i + 1 < len(d) else np.nan
            net = close.iloc[i + 1] / close.iloc[i - 1] - 1 if i + 1 < len(d) else np.nan
            extremes.append(dict(ID=asset, date=date, previous_date=prev,
                                 calendar_days=(date - prev).days,
                                 intervening_weekdays=len(weekday_gap(prev, date)),
                                 previous_close=close.iloc[i - 1], **d.loc[date].to_dict(),
                                 close_change=r.loc[date], robust_z=z.loc[date],
                                 absolute_flag=bool(abs(r.loc[date]) >= ABS_MOVE),
                                 robust_flag=bool(abs(z.loc[date]) >= ROBUST_Z),
                                 next_date=next_date, next_change=next_r, two_observation_change=net,
                                 reversal_candidate=bool(abs(r.loc[date]) >= ABS_MOVE and
                                                        r.loc[date] * next_r < 0 and
                                                        abs(net) <= .2 * abs(r.loc[date])),
                                 ohlc_inconsistent=bool(invalid.loc[date])))
        for a, b in zip(d.index[:-1], d.index[1:]):
            # Most intervals are consecutive days or ordinary weekends.
            if (b - a).days <= 1:
                continue
            missing_days = weekday_gap(a, b)
            if not len(missing_days):
                continue
            missing_weekdays.extend((day, asset) for day in missing_days)
            gaps.append(dict(ID=asset, previous_date=a, next_date=b,
                             calendar_days=(b-a).days, missing_weekdays=len(missing_days),
                             first_missing_weekday=missing_days[0], last_missing_weekday=missing_days[-1],
                             spanning_close_change=close.loc[b] / close.loc[a] - 1,
                             long_gap=len(missing_days) >= 3))
        group = close.ne(close.shift()).cumsum()
        long_groups = group.value_counts().loc[lambda counts: counts >= MIN_STALE_OBS].index
        for _, block in d.loc[group.isin(long_groups)].groupby(group):
            same_ohlc = block[["Open", "High", "Low", "Close"]].nunique().eq(1).all()
            stale.append(dict(ID=asset, start=block.index[0], end=block.index[-1],
                              observations=len(block), unchanged_transitions=len(block)-1,
                              calendar_days=(block.index[-1]-block.index[0]).days,
                              close=block.Close.iloc[0], zero_volume_rows=int(block.Volume.eq(0).sum()),
                              positive_volume_rows=int(block.Volume.gt(0).sum()),
                              identical_ohlc=bool(same_ohlc),
                              all_flat_bars=bool(block.High.eq(block.Low).all()),
                              identical_all_fields=bool(block.nunique().eq(1).all())))
        e = pd.DataFrame({"date": d.index, "close": close.to_numpy()}, index=d.index.to_period("M"))
        endpoints[asset] = e.groupby(level=0).last()
        inventories.append(dict(ID=asset, Name=meta.loc[asset, "Name"],
                                AssetClass=meta.loc[asset, "AssetClass"], rows=len(d),
                                start=d.index.min(), end=d.index.max(),
                                weekend_rows=int((d.index.dayofweek >= 5).sum()),
                                zero_volume_rows=int(d.Volume.eq(0).sum()),
                                zero_open_interest_rows=int(d.OpenInterest.eq(0).sum()),
                                unchanged_close_transitions=int(r.eq(0).sum()),
                                extreme_flags=int(is_extreme.sum()),
                                absolute_move_flags=int(r.abs().ge(ABS_MOVE).sum()),
                                robust_move_flags=int(z.abs().ge(ROBUST_Z).sum()),
                                daily_median=median, daily_mad=mad_r,
                                ohlc_inconsistencies=int(invalid.sum()),
                                negative_activity_rows=int(negative_activity.sum()),
                                nonpositive_price_rows=int(nonpositive.sum())))
    inv = save(inventories, "inventory")
    issue = save(issues, "price_issues")
    extreme = save(pd.DataFrame(extremes).sort_values("close_change", key=abs, ascending=False), "extreme_moves")
    gap = save(pd.DataFrame(gaps).sort_values(["missing_weekdays", "ID"], ascending=[False, True]), "calendar_gaps")
    st = save(pd.DataFrame(stale).sort_values(["observations", "ID"], ascending=[False, True]), "stale_runs")

    # Peer calendar evidence helps distinguish broad closure dates from isolated gaps.
    absent = pd.DataFrame(missing_weekdays, columns=["date", "ID"])
    daily_absence = []
    for day, block in absent.groupby("date"):
        eligible = [a for a, d in data.items() if d.index.min() < day < d.index.max()]
        present = [a for a in eligible if day in data[a].index]
        daily_absence.append(dict(date=day, active_instruments=len(eligible),
                                  absent_instruments=len(block), observed_instruments=len(present),
                                  absent_fraction=len(block)/len(eligible),
                                  absent_IDs=";".join(sorted(block.ID))))
    save(pd.DataFrame(daily_absence).sort_values(["absent_fraction", "date"], ascending=[False, True]), "weekday_absence")
    peer_by_day = pd.DataFrame(daily_absence).set_index("date")
    long_gap_review = gap.loc[gap.long_gap].copy()
    for idx, row in long_gap_review.iterrows():
        days = pd.bdate_range(row.first_missing_weekday, row.last_missing_weekday)
        peer = peer_by_day.loc[days]
        long_gap_review.loc[idx, "min_absent_fraction"] = peer.absent_fraction.min()
        long_gap_review.loc[idx, "max_absent_fraction"] = peer.absent_fraction.max()
        long_gap_review.loc[idx, "weekdays_only_this_instrument_absent"] = int(peer.absent_instruments.eq(1).sum())
    save(long_gap_review, "long_gap_review")
    review_context = []
    review_events = [(row.ID, pd.Timestamp(row.date), "OHLC_or_value_issue") for row in issue.itertuples(index=False)]
    review_events += [(row.ID, pd.Timestamp(row.date), "reversal_candidate")
                      for row in extreme.loc[extreme.reversal_candidate].itertuples(index=False)]
    for asset, date, reason in review_events:
        d = data[asset]
        i = d.index.get_loc(date)
        block = d.iloc[max(0, i-2):i+3].copy()
        block.insert(0, "date", block.index)
        block.insert(0, "event_date", date)
        block.insert(0, "review_reason", reason)
        block.insert(0, "ID", asset)
        review_context.append(block.reset_index(drop=True))
    save(pd.concat(review_context, ignore_index=True), "price_review_context")

    # Trace only existing monthly flags; do not introduce a reconstruction/merge policy.
    traces, contexts = [], []
    for row in flagged.itertuples(index=False):
        asset, month = row.ID, pd.Period(row.month, freq="M")
        supplied = float(returns.loc[month, asset])
        saved = float(flagged.loc[(flagged.ID == asset) & (flagged.month == str(month)), "return"].iloc[0])
        assert abs(supplied - saved) < MATCH_TOL
        d, e = data[asset], endpoints[asset]
        current, previous = e.loc[month] if month in e.index else None, e.loc[month-1] if month-1 in e.index else None
        ratio = current.close / previous.close - 1 if current is not None and previous is not None else np.nan
        in_month = d.index.to_period("M") == month
        mr = moves[asset].loc[in_month]
        max_date = mr.abs().idxmax() if mr.notna().any() else pd.NaT
        mext = extreme.loc[(extreme.ID == asset) & (pd.to_datetime(extreme.date).dt.to_period("M") == month)]
        mst = st.loc[(st.ID == asset) & (pd.to_datetime(st.start) <= month.end_time) &
                    (pd.to_datetime(st.end) >= month.start_time)]
        mgaps = gap.loc[(gap.ID == asset) & (pd.to_datetime(gap.first_missing_weekday) <= month.end_time) &
                       (pd.to_datetime(gap.last_missing_weekday) >= month.start_time)]
        traces.append(dict(ID=asset, month=str(month), supplied_return=supplied,
                           previous_price_date=previous.date if previous is not None else pd.NaT,
                           previous_close=previous.close if previous is not None else np.nan,
                           current_price_date=current.date if current is not None else pd.NaT,
                           current_close=current.close if current is not None else np.nan,
                           previous_endpoint_age_days=((month-1).end_time.normalize()-previous.date).days if previous is not None else np.nan,
                           current_endpoint_age_days=(month.end_time.normalize()-current.date).days if current is not None else np.nan,
                           raw_month_end_ratio=ratio, difference=supplied-ratio,
                           matches_raw_endpoints=bool(np.isfinite(ratio) and abs(supplied-ratio) <= MATCH_TOL),
                           daily_observations=int(in_month.sum()), extreme_daily_flags=len(mext),
                           largest_daily_change_date=max_date,
                           largest_daily_change=mr.loc[max_date] if pd.notna(max_date) else np.nan,
                           stale_runs_overlapping=len(mst), weekday_gap_intervals=len(mgaps),
                           long_gap_intervals=int(mgaps.long_gap.sum())))
        start = previous.date if previous is not None else month.start_time
        context = d.loc[start:month.end_time + pd.Timedelta(days=7)].head(int(in_month.sum()) + 4).copy()
        context.insert(0, "close_change", moves[asset].reindex(context.index))
        context.insert(0, "date", context.index)
        context.insert(0, "flagged_month", str(month))
        context.insert(0, "ID", asset)
        contexts.append(context.reset_index(drop=True))
    trace = save(traces, "monthly_outlier_trace")
    save(pd.concat(contexts, ignore_index=True), "monthly_outlier_daily_context")

    missing_traces = []
    for row in internal.itertuples(index=False):
        month, asset = pd.Period(row.month, freq="M"), row.ID
        e, d = endpoints[asset], data[asset]
        record = dict(ID=asset, month=str(month), current_month_rows=int((d.index.to_period("M") == month).sum()))
        for label, period in [("previous", month-1), ("current", month)]:
            record[f"{label}_price_date"] = e.loc[period, "date"] if period in e.index else pd.NaT
            record[f"{label}_endpoint_age_days"] = (period.end_time.normalize()-e.loc[period, "date"]).days if period in e.index else np.nan
        record["both_months_have_prices"] = month in e.index and month-1 in e.index
        record["endpoint_older_than_three_days"] = (record["previous_endpoint_age_days"] > 3 or
                                                     record["current_endpoint_age_days"] > 3)
        missing_traces.append(record)
    missing_trace = save(missing_traces, "monthly_missing_trace")
    ending = []
    for asset in returns:
        if pd.isna(returns.iloc[-1][asset]):
            d = data[asset]
            ending.append(dict(ID=asset, last_raw_date=d.index[-1], last_supplied_month=str(returns[asset].last_valid_index()),
                               december_2014_raw_rows=int((d.index.to_period("M") == pd.Period("2014-12")).sum()),
                               days_before_december_end=(pd.Timestamp("2014-12-31")-d.index[-1]).days))
    save(ending, "trailing_missing_trace")
    assert len(trace) == len(flagged) == len(expected)
    assert len(missing_trace) == len(internal)
    assert all(digest(ROOT / name) == sha for name, sha in before.items()), "Source changed during audit"
    save([dict(path=name, sha256=sha) for name, sha in before.items()], "source_manifest")
    summary = dict(files=len(paths), rows=int(inv.rows.sum()),
                   date_start=str(inv.start.min().date()), date_end=str(inv.end.max().date()),
                   ohlc_inconsistent_rows=int(inv.ohlc_inconsistencies.sum()),
                   nonpositive_price_rows=int(inv.nonpositive_price_rows.sum()),
                   negative_activity_rows=int(inv.negative_activity_rows.sum()),
                   weekend_rows=int(inv.weekend_rows.sum()),
                   extreme_flags=len(extreme), absolute_10pct_flags=int(extreme.absolute_flag.sum()),
                   robust_z_10_flags=int(extreme.robust_flag.sum()),
                   flagged_moves_spanning_missing_weekdays=int(extreme.intervening_weekdays.gt(0).sum()),
                   reversal_candidates=int(extreme.reversal_candidate.sum()),
                   weekday_gap_intervals=len(gap), missing_weekday_cells=len(absent),
                   long_gap_intervals=int(gap.long_gap.sum()),
                   stale_runs=len(st), stale_instruments=int(st.ID.nunique()),
                   identical_ohlc_runs=int(st.identical_ohlc.sum()),
                   identical_all_fields_runs=int(st.identical_all_fields.sum()),
                   monthly_flags=len(trace), monthly_endpoint_matches=int(trace.matches_raw_endpoints.sum()),
                   internal_monthly_gaps=len(missing_trace),
                   gaps_with_both_raw_months=int(missing_trace.both_months_have_prices.sum()),
                   gaps_with_endpoint_older_than_three_days=int(missing_trace.endpoint_older_than_three_days.sum()),
                   thresholds=dict(absolute_daily_move=ABS_MOVE, daily_robust_z=ROBUST_Z,
                                   stale_min_observations=MIN_STALE_OBS, long_gap_missing_weekdays=3,
                                   monthly_return_absolute_tolerance=MATCH_TOL),
                   source_hashes_unchanged=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
