import numpy as np
import pandas as pd
import pytest

from src.risk_model.rescale import trailing_scale


def test_scale_window_and_lag_count_calendar_months_across_zero_risk_gaps():
    months = pd.period_range("2020-01", periods=8, freq="M")
    calendar = pd.Series([1, 2, np.nan, 8, 4, np.nan, 3, 6], index=months)
    observed = calendar.dropna()
    expected = calendar.rolling(3, min_periods=2).std(ddof=1).shift(2).fillna(1.0)
    pd.testing.assert_series_equal(trailing_scale(observed, 3, 2, 2), expected)
    assert trailing_scale(observed, 3, 2, 2).loc["2020-07"] == pytest.approx(
        calendar.loc["2020-03":"2020-05"].std(ddof=1)
    )


def test_gap_scale_is_invariant_to_future_mutations():
    months = pd.period_range("2020-01", periods=8, freq="M")
    z = pd.Series([1, 2, 8, 4, 3, 6], index=months[[0, 1, 3, 4, 6, 7]])
    changed = z.copy()
    changed.loc["2020-07":] = 100
    pd.testing.assert_series_equal(
        trailing_scale(z, 3, 2, 2).loc[:"2020-07"],
        trailing_scale(changed, 3, 2, 2).loc[:"2020-07"],
    )
