"""Map month-end anchors to the latest raw daily close within a lookback."""

import numpy as np
import pandas as pd


def close_frames(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a daily Close panel into one Close frame per market, over its own history."""
    return {market: prices[market].dropna().to_frame("Close") for market in prices.columns}


def endpoints(data, months, anchor_kind="weekday", lookback=3, age_kind="calendar"):
    """Select the latest sufficiently fresh close known at each month-end anchor.

    The last date in a full file is not evidence available at an earlier anchor.
    A close may be carried at most ``lookback`` days; this does not prove the
    market was open or the contract remained tradable at the anchor.
    """
    if data.empty or not data.index.is_monotonic_increasing or not data.index.is_unique:
        raise ValueError("Endpoint prices require a nonempty, ordered, unique date index")
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
        ages[have_prior] = np.busday_count(
            dates[have_prior].to_numpy().astype("datetime64[D]"),
            anchors[have_prior].to_numpy().astype("datetime64[D]"),
        )
    valid = have_prior & (ages <= lookback)
    # Do not expose the first future close as an apparent historical observation.
    closes = data.Close.iloc[chosen].where(have_prior).to_numpy()
    table = pd.DataFrame(
        {
            "target_date": anchors,
            "price_date": dates,
            "age": ages,
            "endpoint_accepted": valid,
            "raw_close": closes,
        },
        index=months,
    )
    table["endpoint_close"] = table.raw_close.where(valid)
    return table


def historical_span_endpoints(
    data, months, anchor_kind="weekday", lookback=3, bound_span=True, age_kind="calendar"
):
    """Reproduce the old full-file span rule for historical reconciliation only.

    This rule uses the last date in the complete file. It is retrospective and
    must not be used to construct strategy inputs or evaluate performance.
    """
    table = endpoints(data, months, anchor_kind, lookback, age_kind)
    anchors = table.target_date
    within_span = (anchors >= data.index[0]) & (anchors <= data.index[-1])
    table["target_inside_raw_span"] = within_span
    if bound_span:
        table["endpoint_accepted"] &= within_span
        table["endpoint_close"] = table.raw_close.where(table.endpoint_accepted)
    return table
