"""Map month-end anchors to the latest raw daily close within a lookback."""
import numpy as np
import pandas as pd


def endpoints(data, months, anchor_kind="weekday", lookback=3, bound_span=True,
              age_kind="calendar"):
    anchors = months.to_timestamp("M")
    if anchor_kind == "weekday":
        anchors = pd.DatetimeIndex([pd.offsets.BMonthEnd().rollback(d) for d in anchors])
    positions = data.index.searchsorted(anchors, side="right") - 1
    have_prior = positions >= 0
    chosen = np.maximum(positions, 0)
    dates = pd.DatetimeIndex(data.index[chosen]).where(have_prior)
    ages = np.asarray((anchors - dates).days, dtype=float)
    if age_kind == "weekdays":
        ages = np.full(len(months), np.nan)
        ages[have_prior] = np.busday_count(dates[have_prior].to_numpy().astype("datetime64[D]"),
                                         anchors[have_prior].to_numpy().astype("datetime64[D]"))
    within_span = (anchors >= data.index[0]) & (anchors <= data.index[-1])
    valid = have_prior & (ages <= lookback)
    if bound_span:
        valid &= within_span
    table = pd.DataFrame({"target_date": anchors, "price_date": dates,
                          "age": ages, "target_inside_raw_span": within_span,
                          "endpoint_accepted": valid,
                          "raw_close": data.Close.iloc[chosen].to_numpy()}, index=months)
    table["endpoint_close"] = table.raw_close.where(valid)
    return table
