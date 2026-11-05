"""Descriptive activity fields and strictly lagged, source-specific diagnostics."""

import numpy as np
import pandas as pd


def activity_summary(frame, repeat_screen):
    volume, oi = frame.Volume, frame.OpenInterest
    repeated = frame.eq(frame.shift()).all(axis=1)
    groups = frame.ne(frame.shift()).any(axis=1).cumsum()
    sizes = groups.map(groups.value_counts())
    return dict(
        observations=len(frame),
        start=str(frame.index.min().date()),
        end=str(frame.index.max().date()),
        zero_volume=int(volume.eq(0).sum()),
        negative_volume=int(volume.lt(0).sum()),
        zero_open_interest=int(oi.eq(0).sum()),
        negative_open_interest=int(oi.lt(0).sum()),
        fractional_volume=int(volume.mod(1).ne(0).sum()),
        repeated_full_bars=int(repeated.sum()),
        longest_identical_bar_run=int(sizes.max()),
        rows_in_long_identical_runs=int(sizes.ge(repeat_screen).sum()),
        median_reported_volume=float(volume.median()),
        median_reported_oi=float(oi.median()),
    )


def lagged_activity(frame, months, lookback, lag_bars, stale_days):
    """Exclude lag_bars latest observations dated before each holding month."""
    if lookback < 1 or lag_bars < 1 or stale_days < 0:
        raise ValueError("Require positive lookback/lag and nonnegative age screen")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Activity dates must be unique and sorted")
    rows = []
    for month in months:
        stop = frame.index.searchsorted(month.start_time, side="left")
        end = max(0, stop - lag_bars)
        window = frame.iloc[max(0, end - lookback) : end]
        last = window.index[-1] if len(window) else pd.NaT
        latest = frame.index[stop - 1] if stop else pd.NaT
        age = (month.start_time - last).days if len(window) else np.nan
        valid = (
            len(window) == lookback
            and np.isfinite(window.Volume).all()
            and window.Volume.ge(0).all()
        )
        mean = float(window.Volume.mean()) if valid else np.nan
        rows.append(
            dict(
                month=month,
                latest_pre_month_bar=latest,
                history_through=last,
                observations=len(window),
                history_age_days=age,
                history_span_days=(last - window.index[0]).days if len(window) else np.nan,
                mean_reported_volume=mean,
                zero_volume_bars=int(window.Volume.eq(0).sum()),
                latest_reported_oi=float(window.OpenInterest.iloc[-1]) if len(window) else np.nan,
                complete_nonnegative_window=bool(valid),
                stale=bool(len(window) and age > stale_days),
                positive_recent_volume_screen=bool(valid and mean > 0 and age <= stale_days),
            )
        )
    return pd.DataFrame(rows).set_index("month")


def map_trade_sources(events, source):
    """A source-close uses the old series; other beginning trades use the new/current series."""
    selected = events.loc[events.timing.eq("beginning")].copy()
    previous = source.shift(1)
    labels = []
    for row in selected.itertuples():
        month = pd.Period(row.month, "M")
        panel = previous if row.event == "source_close" else source
        label = panel.loc[month, row.market]
        if pd.isna(label):
            raise ValueError("Missing predeclared execution source")
        labels.append(label)
    selected["source_series"] = labels
    return selected


def collateral_rates(frame, months):
    """Keep the supplied decimal monthly RF; fail rather than extending/filling coverage."""
    dates = pd.to_datetime(frame.Date, errors="raise").dt.to_period("M")
    if dates.duplicated().any():
        raise ValueError("Duplicate monthly RF observations")
    rates = pd.Series(pd.to_numeric(frame.RF, errors="raise").to_numpy(), index=dates, name="RF")
    rates = rates.reindex(months)
    if not np.isfinite(rates).all() or rates.le(-1).any():
        raise ValueError("Missing or invalid monthly RF coverage")
    return rates
