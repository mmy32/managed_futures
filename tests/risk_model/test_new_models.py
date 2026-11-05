import numpy as np
import pandas as pd
import pytest

from src.models import MarketData
from src.risk_model import (
    DailyCovarianceRiskModel,
    DccGarchRiskModel,
    RollingCovarianceRiskModel,
    ScaledRiskModel,
    trailing_scale,
)
from src.risk_model.garch import fit_pooled_garch, garch_variance


def monthly_data(months=60, markets=4, seed=3):
    rng = np.random.default_rng(seed)
    index = pd.period_range("2000-01", periods=months, freq="M")
    common = rng.normal(0, 0.02, months)
    returns = pd.DataFrame(
        common[:, None] + rng.normal(0, 0.03, (months, markets)),
        index=index,
        columns=list("ABCDEFGH")[:markets],
    )
    meta = pd.DataFrame(
        {"AssetClass": ["EQ", "EQ", "FI", "FI", "FX", "FX", "COMM", "COMM"][:markets]},
        index=returns.columns,
    )
    return MarketData(returns, meta)


def daily_frame(columns, start="1999-12-01", end="2005-12-31", seed=5):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start, end)
    common = rng.normal(0, 0.006, len(index))
    return pd.DataFrame(
        common[:, None] + rng.normal(0, 0.008, (len(index), len(columns))),
        index=index,
        columns=columns,
    )


def eligible_from(data, window=36, lag=1):
    full = data.returns.notna().astype(int).rolling(window).sum() == window
    return full.shift(lag, fill_value=False)


def test_default_correlation_weights_match_the_single_weighting():
    data = monthly_data()
    eligible = eligible_from(data).loc["2003-06":"2003-08"]
    kwargs = {"window": 36, "lag": 1, "volatility_floor": 0.02, "correlation_shrinkage": 0.5}
    same, _ = RollingCovarianceRiskModel(**kwargs, half_lives=(12,)).covariances(data, eligible)
    explicit, _ = RollingCovarianceRiskModel(
        **kwargs, half_lives=(12,), correlation_half_lives=(12,)
    ).covariances(data, eligible)
    for month in same:
        np.testing.assert_allclose(same[month], explicit[month])


def test_separate_correlation_weighting_changes_correlation_not_volatility():
    data = monthly_data()
    eligible = eligible_from(data).loc["2003-06":"2003-06"]
    kwargs = {"window": 36, "lag": 1, "volatility_floor": 0.0, "correlation_shrinkage": 0.5}
    (a,), (b,) = (
        RollingCovarianceRiskModel(**kwargs, correlation_half_lives=h)
        .covariances(data, eligible)[0]
        .values()
        for h in ((None,), (4,))
    )
    np.testing.assert_allclose(np.diag(a), np.diag(b))
    assert not np.allclose(a, b)


def test_daily_model_is_positive_definite_and_ignores_the_future():
    data = monthly_data()
    daily = daily_frame(data.returns.columns)
    eligible = eligible_from(data).loc["2003-06":"2003-06"]
    model = DailyCovarianceRiskModel(daily, 36, 1, 0.02, 0.5)
    (matrix,) = model.covariances(data, eligible)[0].values()
    assert np.linalg.eigvalsh(matrix).min() > 0
    changed = daily.copy()
    changed.loc["2003-06-01":] = 0.5
    (again,) = (
        DailyCovarianceRiskModel(changed, 36, 1, 0.02, 0.5).covariances(data, eligible)[0].values()
    )
    np.testing.assert_allclose(matrix, again)


def test_daily_volatility_is_missing_where_the_daily_window_has_gaps():
    data = monthly_data()
    daily = daily_frame(data.returns.columns)
    daily.loc["2002-03-04":"2002-03-15", "B"] = np.nan
    vol = DailyCovarianceRiskModel(daily, 36, 1, 0.02, 0.5).volatility(data)
    assert vol.loc["2003-03":"2005-02", "B"].isna().all()
    assert vol.loc["2003-03":"2005-02", "A"].notna().all()


def test_garch_variance_matches_the_recursion():
    returns = np.random.default_rng(1).normal(0, 0.01, 50)
    omega, alpha, beta, start = 2e-6, 0.07, 0.9, 1e-4
    expected = [omega + alpha * start + beta * start]
    for t in range(1, 51):
        expected.append(omega + alpha * returns[t - 1] ** 2 + beta * expected[-1])
    np.testing.assert_allclose(garch_variance(returns, omega, alpha, beta, start), expected)


def test_pooled_garch_recovers_persistence_from_simulated_data():
    rng = np.random.default_rng(7)
    alpha, beta, omega = 0.08, 0.90, 2e-6
    series = []
    for _ in range(4):
        h, r = omega / (1 - alpha - beta), []
        for _ in range(4000):
            r.append(np.sqrt(h) * rng.normal())
            h = omega + alpha * r[-1] ** 2 + beta * h
        series.append(np.array(r))
    fitted = fit_pooled_garch(series)
    assert fitted.alpha + fitted.beta == pytest.approx(0.98, abs=0.02)
    assert fitted.alpha == pytest.approx(alpha, abs=0.03)


def test_dcc_garch_forecast_ignores_the_future_and_is_positive_definite():
    data = monthly_data(months=90)
    columns = list(data.returns.columns)
    daily = daily_frame(columns, start="1999-01-01", end="2007-06-30")
    meta = data.meta.AssetClass
    eligible = eligible_from(data).loc["2004-06":"2004-06"]
    model = DccGarchRiskModel(daily, meta, 36, 1, 0.02, 0.5)
    (matrix,) = model.covariances(data, eligible)[0].values()
    assert np.linalg.eigvalsh(matrix).min() > 0
    changed = daily.copy()
    changed.loc["2004-06-01":] = 0.3
    other = DccGarchRiskModel(changed, meta, 36, 1, 0.02, 0.5)
    (again,) = other.covariances(data, eligible)[0].values()
    np.testing.assert_allclose(matrix, again)


def test_trailing_scale_uses_past_months_only_and_defaults_to_one():
    z = pd.Series(
        np.random.default_rng(2).normal(0, 1.3, 80),
        index=pd.period_range("2000-01", periods=80, freq="M"),
    )
    scale = trailing_scale(z, window=36, minimum=24)
    assert (scale.iloc[:24] == 1.0).all()
    assert scale.iloc[40] == pytest.approx(z.iloc[4:40].std(ddof=1))
    altered = z.copy()
    altered.iloc[40:] = 99
    np.testing.assert_allclose(trailing_scale(altered, 36, 24).iloc[:41], scale.iloc[:41])


def test_scaled_model_scales_covariance_but_not_volatility():
    data = monthly_data()
    eligible = eligible_from(data).loc["2003-06":"2003-07"]
    base = RollingCovarianceRiskModel(36, 1, 0.02, 0.5)
    scale = pd.Series(1.5, index=data.returns.index)
    scaled = ScaledRiskModel(base, scale)
    plain, _ = base.covariances(data, eligible)
    bigger, _ = scaled.covariances(data, eligible)
    for month in plain:
        np.testing.assert_allclose(bigger[month], plain[month] * 2.25)
    pd.testing.assert_frame_equal(scaled.volatility(data), base.volatility(data))
    with pytest.raises(ValueError):
        ScaledRiskModel(base, scale * 0)
