import numpy as np
import pandas as pd
import pytest

from src.alpha_model import AlwaysLongSignal, CompoundedReturnSignal, SumReturnSignal, lagged


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
