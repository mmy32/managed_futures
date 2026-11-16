import numpy as np
import pandas as pd
import pytest

from src.models import MarketData
from src.risk_model.daily import DailyCovarianceRiskModel, daily_returns


def test_missing_quote_is_not_a_zero_or_an_invented_one_day_return():
    dates = pd.bdate_range("2020-01-06", periods=5)
    prices = pd.DataFrame({"A": [100, 101, np.nan, 104, 105],
                           "B": [200, 202, 204, 206, 208]}, index=dates)
    original = prices.copy(deep=True)
    returns = daily_returns(prices)
    assert returns.loc[dates[1], "A"] == pytest.approx(0.01)
    assert returns.loc[dates[2:4], "A"].isna().all()
    assert returns.loc[dates[4], "A"] == pytest.approx(105 / 104 - 1)
    assert returns.loc[dates[2], "B"] == pytest.approx(204 / 202 - 1)
    pd.testing.assert_frame_equal(prices, original)


def test_daily_return_prefix_is_unchanged_by_future_quotes():
    dates = pd.bdate_range("2020-01-06", periods=5)
    prices = pd.DataFrame({"A": [100, np.nan, 102, 103, 104]}, index=dates)
    full = daily_returns(prices)
    prefix = daily_returns(prices.iloc[:3])
    pd.testing.assert_frame_equal(full.iloc[:3], prefix)


@pytest.mark.parametrize("bad", [0.0, -1.0, np.inf, -np.inf])
def test_daily_return_boundary_rejects_invalid_observed_prices(bad):
    prices = pd.DataFrame({"A": [100, bad]}, index=pd.bdate_range("2020-01-06", periods=2))
    with pytest.raises(ValueError, match="positive and finite"):
        daily_returns(prices)


def test_daily_covariance_keeps_excluded_monthly_columns_ineligible():
    months = pd.period_range("2020-01", periods=6, freq="M")
    returns = pd.DataFrame({"A": 0.01, "EC": 0.02}, index=months)
    meta = pd.DataFrame({"AssetClass": ["EQ", "FX"]}, index=returns.columns)
    dates = pd.bdate_range("2020-01-01", "2020-06-30")
    daily = pd.DataFrame({"A": np.random.default_rng(4).normal(0, 0.01, len(dates))},
                         index=dates)
    model = DailyCovarianceRiskModel(daily, 2, 1, 0.02, 0.5)
    vol = model.volatility(MarketData(returns, meta))
    assert vol.A.notna().any()
    assert vol.EC.isna().all()
