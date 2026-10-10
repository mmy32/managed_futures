import numpy as np
import pandas as pd
import pytest

from src.models import MarketData
from src.risk_model import (
    EwmaVolatilityRiskModel,
    RollingCovarianceRiskModel,
    ewma_daily_volatility,
)


def daily_prices(days=1500, markets=("A", "B"), seed=5):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2005-01-03", periods=days)
    steps = rng.normal(0.0002, 0.01, (days, len(markets)))
    return pd.DataFrame(100 * np.cumprod(1 + steps, axis=0), index=index, columns=markets)


def loop_volatility(prices, center_of_mass=60, trading_days=261):
    """Eq. 1 of the paper as a direct weighted sum, via the recursion's explicit weights."""
    returns = prices.pct_change().dropna().to_numpy()
    delta = center_of_mass / (1 + center_of_mass)
    out = np.full(len(returns), np.nan)
    for t in range(len(returns)):
        past = returns[: t + 1][::-1]
        weights = delta ** np.arange(len(past))
        weights = weights / weights.sum()
        mean = (weights * past).sum()
        out[t] = np.sqrt(trading_days * (weights * (past - mean) ** 2).sum())
    return out


def test_ewma_matches_loop_implementation():
    prices = daily_prices(1500)["A"]
    expected = loop_volatility(prices)
    result = ewma_daily_volatility(prices, min_observations=1)
    # The recursion puts the unobserved tail weight on the first return; at 1500 days it is ~e-11.
    np.testing.assert_allclose(result.to_numpy()[-100:], expected[-100:], rtol=1e-6)


def test_ewma_requires_minimum_history():
    result = ewma_daily_volatility(daily_prices(200)["A"], min_observations=60)
    assert result.iloc[:58].isna().all()
    assert result.iloc[-1] > 0


def monthly_data(prices):
    months = pd.period_range("2005-01", prices.index[-1].to_period("M"), freq="M")
    returns = pd.DataFrame(0.0, index=months, columns=prices.columns)
    meta = pd.DataFrame({"AssetClass": "EQ"}, index=prices.columns)
    return MarketData(returns, meta, prices)


def test_monthly_volatility_uses_only_the_prior_month_end():
    prices = daily_prices()
    data = monthly_data(prices)
    vol = EwmaVolatilityRiskModel(lag=1).volatility(data)
    daily = ewma_daily_volatility(prices["A"])
    month = pd.Period("2008-06", "M")
    expected = daily.loc[: str(month - 1)].iloc[-1]
    assert vol.loc[month, "A"] == pytest.approx(expected)


def test_future_prices_cannot_change_past_volatility():
    prices = daily_prices()
    changed = prices.copy()
    changed.loc["2009-01-01":, "A"] *= 3
    model = EwmaVolatilityRiskModel(lag=1)
    before = model.volatility(monthly_data(prices))
    after = model.volatility(monthly_data(changed))
    pd.testing.assert_frame_equal(before.loc[:"2008-12"], after.loc[:"2008-12"])


def test_ewma_needs_daily_prices_and_a_positive_lag():
    data = monthly_data(daily_prices())
    with pytest.raises(ValueError, match="daily prices"):
        EwmaVolatilityRiskModel(lag=1).volatility(MarketData(data.returns, data.meta))
    with pytest.raises(ValueError):
        EwmaVolatilityRiskModel(lag=0)


def test_both_risk_models_satisfy_one_interface():
    prices = daily_prices()
    data = monthly_data(prices)
    rng = np.random.default_rng(2)
    data = MarketData(
        pd.DataFrame(
            rng.normal(0, 0.03, data.returns.shape),
            index=data.returns.index,
            columns=data.returns.columns,
        ),
        data.meta,
        prices,
    )
    models = [
        RollingCovarianceRiskModel(
            window=24, lag=1, volatility_floor=0.02, correlation_shrinkage=0.5
        ),
        EwmaVolatilityRiskModel(lag=1),
    ]
    month = pd.Period("2008-06", "M")
    for model in models:
        vol = model.volatility(data)
        assert list(vol.columns) == ["A", "B"] and vol.index.equals(data.returns.index)
        eligible = vol.loc[[month]].notna() & True
        matrices, details = model.covariances(data, eligible)
        assert matrices[month].shape == (2, 2)
        assert np.linalg.eigvalsh(matrices[month]).min() > 0
        assert {"information_through", "estimation_start", "min_eigenvalue"} <= details[
            month
        ].keys()
