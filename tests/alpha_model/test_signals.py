import numpy as np
import pandas as pd
import pytest

from src.alpha_model import (
    AlwaysLongLike,
    AlwaysLongSignal,
    AssetClassSignal,
    CompoundedReturnSignal,
    SkipMonthSignal,
    SumReturnSignal,
    lagged,
)


def monthly(values):
    index = pd.period_range("2000-01", periods=len(values), freq="M")
    return pd.DataFrame({"A": values}, index=index)


def test_sum_and_compounded_signals_disagree_when_compounding_flips_the_sign():
    # Sum = +0.01 > 0, but (1.5)(0.5) - 1 = -0.25 < 0.
    returns = monthly([0.5, -0.49])
    assert SumReturnSignal(2).forecast(returns)["A"].iloc[-1] == 1
    assert CompoundedReturnSignal(2).forecast(returns)["A"].iloc[-1] == -1


def test_compounded_signal_matches_explicit_product():
    rng = np.random.default_rng(1)
    returns = monthly(rng.normal(0, 0.05, 40))
    signal = CompoundedReturnSignal(12).forecast(returns)["A"]
    expected = np.sign((1 + returns["A"]).rolling(12).apply(np.prod, raw=True) - 1)
    pd.testing.assert_series_equal(signal, expected, check_names=False)


@pytest.mark.parametrize("cls", [SumReturnSignal, CompoundedReturnSignal, AlwaysLongSignal])
def test_no_forecast_without_a_full_window(cls):
    forecast = cls(3).forecast(monthly([0.01, 0.02, np.nan, 0.01, 0.01, 0.01]))["A"]
    assert forecast.iloc[:4].isna().all()
    assert forecast.iloc[5] in (-1, 1)


def test_always_long_is_one_where_window_is_complete():
    forecast = AlwaysLongSignal(2).forecast(monthly([0.1, -0.2, 0.3]))["A"]
    assert forecast.isna().iloc[0]
    assert forecast.iloc[1:].eq(1).all()


def test_compounded_signal_rejects_total_loss():
    with pytest.raises(ValueError, match="-100%"):
        CompoundedReturnSignal(2).forecast(monthly([0.1, -1.0, 0.1]))


def test_lag_shifts_forecast_forward_and_must_be_positive():
    forecast = SumReturnSignal(1).forecast(monthly([0.1, -0.1, 0.1]))
    assert lagged(forecast, 1)["A"].tolist()[1:] == [1, -1]
    with pytest.raises(ValueError):
        lagged(forecast, 0)


def test_skip_month_ignores_the_latest_month():
    # The latest month (-50%) would flip the 3-month sign; skipping it keeps the two earlier gains.
    returns = monthly([0.05, 0.05, -0.5])
    assert CompoundedReturnSignal(3).forecast(returns)["A"].iloc[-1] == -1
    assert SkipMonthSignal(3, skip=1).forecast(returns)["A"].iloc[-1] == 1


def test_skip_month_needs_the_full_window_and_matches_explicit_product():
    rng = np.random.default_rng(2)
    returns = monthly(rng.normal(0, 0.05, 30))
    forecast = SkipMonthSignal(12, skip=1).forecast(returns)["A"]
    assert forecast.iloc[:11].isna().all()
    expected = np.sign((1 + returns["A"]).shift(1).rolling(11).apply(np.prod, raw=True) - 1)
    pd.testing.assert_series_equal(forecast, expected, check_names=False)


def test_skip_month_is_unchanged_by_later_returns():
    rng = np.random.default_rng(3)
    returns = monthly(rng.normal(0, 0.05, 30))
    altered = returns.copy()
    altered.iloc[20:] = 0.2
    pd.testing.assert_frame_equal(
        SkipMonthSignal(6).forecast(returns).iloc[:20],
        SkipMonthSignal(6).forecast(altered).iloc[:20],
    )


@pytest.mark.parametrize("lookback, skip", [(3, 0), (3, 3), (0, 1)])
def test_skip_month_rejects_invalid_windows(lookback, skip):
    with pytest.raises(ValueError):
        SkipMonthSignal(lookback, skip)


def test_skip_month_rejects_total_loss():
    with pytest.raises(ValueError, match="-100%"):
        SkipMonthSignal(3).forecast(monthly([0.1, -1.0, 0.1]))


def test_asset_class_signal_routes_each_market_to_its_class_signal():
    index = pd.period_range("2000-01", periods=4, freq="M")
    returns = pd.DataFrame(
        {"EQ1": [0.1, 0.1, -0.5, 0.0], "FX1": [0.1, 0.1, -0.5, 0.0], "CM1": [-0.1] * 4}, index=index
    )
    classes = pd.Series({"EQ1": "EQ", "FX1": "FX", "CM1": "COMM"})
    routed = AssetClassSignal(
        {"EQ": SkipMonthSignal(3), "FX": SumReturnSignal(1), "COMM": SumReturnSignal(2)}, classes
    ).forecast(returns)
    assert list(routed.columns) == ["EQ1", "FX1", "CM1"]
    assert routed["EQ1"].iloc[2] == 1  # skip-month ignores the -50%
    assert routed["FX1"].iloc[2] == -1  # one-month sum sees it
    assert routed["CM1"].iloc[-1] == -1


def test_asset_class_signal_rejects_a_market_without_a_signal():
    returns = monthly([0.1, 0.1, 0.1])
    with pytest.raises(ValueError, match="A"):
        AssetClassSignal({"EQ": SumReturnSignal(1)}, pd.Series({"A": "FI"})).forecast(returns)
    with pytest.raises(ValueError, match="A"):
        AssetClassSignal({"EQ": SumReturnSignal(1)}, pd.Series(dtype=object)).forecast(returns)


def test_always_long_like_is_one_exactly_where_the_reference_has_a_forecast():
    returns = monthly([0.1, 0.1, 0.1, np.nan, 0.1, 0.1])
    reference = SkipMonthSignal(3)  # skips the latest month, so a NaN there still leaves a forecast
    long_like = AlwaysLongLike(reference).forecast(returns)["A"]
    known = reference.forecast(returns)["A"].notna()
    assert long_like.notna().equals(known)
    assert long_like[known].eq(1).all()
