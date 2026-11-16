"""Estimation failures and calendar-preserving missing-observation forecasts."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.models import MarketData
from src.risk_model import DccGarchRiskModel, garch
from tests.risk_model.test_new_models import daily_frame, monthly_data


@pytest.mark.parametrize("failure", [
    {"success": False}, {"fun": np.nan}, {"x": [np.nan, 0.1]}, {"x": [1.1, 0.1]},
])
def test_garch_rejects_failed_or_invalid_optimizer(monkeypatch, failure):
    result = {"success": True, "fun": 1.0, "x": [0.97, 0.06], "message": "test termination", "nit": 2}
    result.update(failure)
    monkeypatch.setattr(garch, "minimize", lambda *args, **kwargs: SimpleNamespace(**result))
    with pytest.raises(ValueError, match="GARCH estimation failed"):
        garch.fit_pooled_garch([np.random.default_rng(4).normal(0, 0.01, 300)])


@pytest.mark.parametrize("failure", [
    {"success": False}, {"fun": np.inf}, {"x": [0.1, 0.95]}, {"x": [-0.1, 0.9]},
])
def test_dcc_rejects_failed_or_nonstationary_optimizer(monkeypatch, failure):
    result = {"success": True, "fun": 1.0, "x": [0.02, 0.95], "message": "test termination", "nit": 2}
    result.update(failure)
    monkeypatch.setattr(garch, "minimize", lambda *args, **kwargs: SimpleNamespace(**result))
    residuals = pd.DataFrame(np.random.default_rng(4).normal(size=(300, 2)))
    with pytest.raises(ValueError, match="DCC estimation failed"):
        garch.fit_dcc(residuals, np.random.default_rng(4))


@pytest.mark.parametrize("history", [np.zeros(300), np.ones(249), np.full(300, np.inf)])
def test_garch_rejects_unestimable_market_history(history):
    with pytest.raises(ValueError, match="positive variance"):
        garch.fit_pooled_garch([history])


def test_missing_garch_day_advances_expected_variance_without_compressing_time():
    returns = np.array([0.03, np.nan, np.nan, -0.01])
    omega, alpha, beta, start = 1e-6, 0.1, 0.8, 1e-4
    expected = [omega + (alpha + beta) * start]
    for value in returns:
        shock = expected[-1] if np.isnan(value) else value**2
        expected.append(omega + alpha * shock + beta * expected[-1])
    actual = garch.garch_variance(returns, omega, alpha, beta, start)
    np.testing.assert_allclose(actual, expected)
    assert actual[-1] != garch.garch_variance(returns[np.isfinite(returns)], omega,
                                             alpha, beta, start)[-1]


def test_long_missing_garch_history_matches_scalar_recursion_across_blocks():
    returns = np.random.default_rng(9).normal(0, 0.01, 1500)
    returns[::19] = np.nan
    returns[250:400] = np.nan
    omega, alpha, beta, start = 1e-6, 0.08, 0.9, 1e-4
    expected = [omega + (alpha+beta)*start]
    for value in returns:
        expected.append(omega + alpha*(expected[-1] if np.isnan(value) else value**2)
                        + beta*expected[-1])
    np.testing.assert_allclose(garch.garch_variance(returns, omega, alpha, beta, start),
                               expected, rtol=1e-12)


def test_missing_dcc_shocks_use_conditional_moments_not_zero():
    q = np.array([[1.0, 0.6], [0.6, 1.0]])
    np.testing.assert_allclose(garch.conditional_residual_moment([np.nan, np.nan], q), q)
    np.testing.assert_allclose(
        garch.conditional_residual_moment([2.0, np.nan], q),
        [[4.0, 2.4], [2.4, 0.64 + 1.44]],
    )
    np.testing.assert_allclose(garch.conditional_residual_moment([2.0, -1.0], q),
                               [[4.0, -2.0], [-2.0, 1.0]])


@pytest.mark.parametrize("missing", [False, True])
def test_dcc_pair_likelihood_matches_conditional_moment_filter(missing):
    left = np.array([0.2, 1.2, -0.5, 0.8, -0.4])
    right = np.array([0.6, -0.2, 0.7, 0.1, 1.2])
    if missing:
        left[1:3], right[2] = np.nan, np.nan
    a, b, target = 0.05, 0.8, 0.3
    q = np.array([[1.0, target], [target, 1.0]])
    total, count = 0.0, 0
    for x, y in zip(left, right, strict=True):
        rho = q[0, 1] / np.sqrt(q[0, 0] * q[1, 1])
        if np.isfinite(x) and np.isfinite(y):
            total += np.log1p(-rho*rho) + (x*x+y*y-2*rho*x*y)/(1-rho*rho)
            count += 1
        moment = garch.conditional_residual_moment([x, y], q)
        q = (1-a-b)*np.array([[1.0, target], [target, 1.0]]) + a*moment + b*q
    actual = garch._dcc_pair_negative_loglik((a, b), [(left, right, target)])
    assert actual == pytest.approx(total/count)


def fixed_fits(monkeypatch):
    monkeypatch.setattr(garch, "fit_pooled_garch",
                        lambda *args, **kwargs: garch.GarchParams(0.05, 0.9))
    monkeypatch.setattr(garch, "fit_dcc", lambda *args, **kwargs: (0.02, 0.95))


def test_dcc_handles_missing_daily_calendar_and_omitted_monthly_markets(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data(months=60)
    daily = daily_frame(list(data.returns), start="1999-01-01", end="2005-12-31")
    daily.loc[daily.index[::19], "B"] = np.nan
    returns = data.returns.assign(EXCLUDED=0.01)
    meta = pd.concat([data.meta, pd.DataFrame({"AssetClass": ["EQ"]}, index=["EXCLUDED"])])
    extended = MarketData(returns, meta)
    model = DccGarchRiskModel(daily, meta.AssetClass, 36, 1, 0.02, 0.1)
    vol = model.volatility(extended)
    assert vol.loc["2003-06", "B"] > 0
    assert vol.EXCLUDED.isna().all()
    record = model.coverage_diagnostics().query("market == 'B'").iloc[-1]
    assert record.missing_daily > 0 and record.observed_daily > 250
    assert record.observed_in_cutoff_month


def test_dcc_cannot_forecast_market_with_no_observations_in_cutoff_month(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data(months=60)
    daily = daily_frame(list(data.returns), start="1999-01-01", end="2005-12-31")
    daily.loc["2003-05-01":, "B"] = np.nan
    model = DccGarchRiskModel(daily, data.meta.AssetClass, 36, 1, 0.02, 0.1)
    assert np.isnan(model.volatility(data).loc["2003-06", "B"])


def test_zero_variance_market_cannot_poison_other_markets_estimation(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data(months=60)
    daily = daily_frame(list(data.returns), start="1999-01-01", end="2005-12-31")
    daily["A"] = 0.0
    model = DccGarchRiskModel(daily, data.meta.AssetClass, 36, 1, 0.02, 0.1)
    vol = model.volatility(data)
    assert vol.A.isna().all()
    assert (vol.loc["2003-06", ["B", "C", "D"]] > 0).all()
    assert model.fitted_parameters().excluded_nonpositive_targets.eq("A").all()


def test_missing_data_filter_ignores_future_values_and_future_gap_patterns(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data(months=60)
    daily = daily_frame(list(data.returns), start="1999-01-01", end="2005-12-31")
    daily.loc[daily.index[::19], "B"] = np.nan
    cutoff = pd.Period("2003-06", freq="M")
    altered = daily.copy()
    altered.loc[cutoff.start_time:] = np.nan
    models = [DccGarchRiskModel(frame, data.meta.AssetClass, 36, 1, 0.02, 0.1)
              for frame in (daily, altered, daily.loc[:cutoff.end_time])]
    eligible = pd.DataFrame(True, index=pd.PeriodIndex([cutoff]), columns=data.returns.columns)
    matrices = [model.covariances(
        MarketData(data.returns.loc[:model.daily.index[-1].to_period("M")], data.meta), eligible
    )[0][cutoff] for model in models]
    for matrix in matrices[1:]:
        np.testing.assert_allclose(matrix, matrices[0])
