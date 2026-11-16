"""Monthly forecast frequency, annual-fit timing, causality and failed-fit controls."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.models import MarketData
from src.risk_model import monthly_garch
from src.risk_model.garch import GarchParams, garch_variance
from src.risk_model.monthly_garch import MonthlyDccGarchRiskModel


def monthly_data(end="2000-06"):
    index = pd.period_range("1990-01", end, freq="M")
    rng = np.random.default_rng(17)
    values = rng.normal(0.003, 0.04, (len(index), 3))
    values[:, 1] += values[:, 0] * 0.3
    returns = pd.DataFrame(values, index=index, columns=["A", "B", "C"])
    meta = pd.DataFrame({"AssetClass": ["EQ", "EQ", "FI"]}, index=returns.columns)
    return MarketData(returns, meta)


def fixed_fits(monkeypatch):
    monkeypatch.setattr(monthly_garch, "fit_monthly_garch",
                        lambda *args, **kwargs: GarchParams(0.08, 0.85))
    monkeypatch.setattr(monthly_garch, "fit_monthly_dcc", lambda *args, **kwargs: (0.04, 0.9))


def make_model(data, **kwargs):
    return MonthlyDccGarchRiskModel(data.meta.AssetClass, forecast_start="2000-01",
                                    pair_count=6, **kwargs)


def test_forecasts_one_month_and_annualizes_by_twelve_once(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data()
    model = make_model(data, volatility_floor=0)
    vol = model.volatility(data)
    history = data.returns.loc[:"1999-12", "A"].to_numpy()
    target = np.mean(history**2)
    one_month = garch_variance(history, target*(1-0.08-0.85), 0.08, 0.85, target)[-1]
    assert vol.loc["2000-01", "A"]**2 == pytest.approx(one_month*12)
    eligible = vol.loc["2000-01":"2000-01"].notna()
    covariance, details = model.covariances(data, eligible)
    assert covariance[pd.Period("2000-01", "M")][0, 0] == pytest.approx(one_month*12)
    assert details[pd.Period("2000-01", "M")]["information_through"] == pd.Period("1999-12", "M")


def test_lag_two_uses_older_january_fit_and_new_fit_in_february(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data("2000-02")
    model = make_model(data, lag=2)
    vol = model.volatility(data)
    params = model.fitted_parameters().set_index("year")
    assert set(params.index) == {1999, 2000}
    assert params.loc[1999, "fit_information_through"] == "1998-12"
    assert params.loc[2000, "fit_information_through"] == "1999-12"
    history = data.returns.loc[:"1999-11", "A"].to_numpy()
    target = (data.returns.loc[:"1998-12", "A"]**2).mean()
    expected = garch_variance(history, target*(1-0.08-0.85), 0.08, 0.85, target)[-1]
    assert vol.loc["2000-01", "A"]**2 == pytest.approx(expected*12)


def test_actual_monthly_fits_ignore_future_values_and_truncation():
    data = monthly_data()
    changed = data.returns.copy()
    changed.loc["2000-03":] *= 3
    panels = [data, MarketData(changed, data.meta),
              MarketData(data.returns.loc[:"2000-03"], data.meta)]
    forecasts, fitted, covariances = [], [], []
    for panel in panels:
        model = make_model(panel)
        forecasts.append(model.volatility(panel).loc[:"2000-03"])
        eligible = forecasts[-1].loc["2000-01":].notna()
        covariances.append(model.covariances(panel, eligible)[0])
        fitted.append(model.fitted_parameters().drop(columns="fit_seconds"))
        record = fitted[-1].iloc[0]
        assert record.dcc_success and record.EQ_success and record.FI_success
        assert record.fit_information_through == "1999-12"
        assert record.dcc_a >= 0 and record.dcc_b >= 0 and record.dcc_a+record.dcc_b < 1
    for frame in forecasts[1:]:
        pd.testing.assert_frame_equal(frame, forecasts[0], rtol=1e-12, atol=1e-12)
    for frame in fitted[1:]:
        pd.testing.assert_frame_equal(frame, fitted[0], rtol=1e-12, atol=1e-12)
    for case in covariances[1:]:
        for month in case:
            np.testing.assert_allclose(case[month], covariances[0][month], rtol=1e-12, atol=1e-12)
            assert np.linalg.eigvalsh(case[month]).min() > 0


def test_missing_month_variance_uses_conditional_shock_without_zero_fill(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data()
    returns = data.returns.copy()
    returns.loc["2000-01", "B"] = np.nan
    panel = MarketData(returns, data.meta)
    model = make_model(panel, window=3)
    vol = model.volatility(panel)
    assert np.isnan(vol.loc["2000-02", "B"])
    history = returns.loc[:"2000-04", "B"].to_numpy()
    target = (returns.loc[:"1999-12", "B"]**2).mean()
    expected = garch_variance(history, target*(1-0.08-0.85), 0.08, 0.85, target)[-1]
    zero = garch_variance(np.nan_to_num(history), target*(1-0.08-0.85), 0.08, 0.85, target)[-1]
    assert vol.loc["2000-05", "B"]**2 == pytest.approx(expected*12)
    assert expected != pytest.approx(zero)


def test_omitted_market_is_never_fitted_or_given_risk_and_inputs_are_immutable(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data()
    original = data.returns.copy(deep=True)
    extra = MarketData(data.returns.assign(EXCLUDED=0.8), data.meta)
    a, b = make_model(data), make_model(extra)
    expected, actual = a.volatility(data), b.volatility(extra)
    pd.testing.assert_frame_equal(actual[expected.columns], expected)
    assert actual.EXCLUDED.isna().all()
    pd.testing.assert_frame_equal(data.returns, original)
    pd.testing.assert_frame_equal(a.fitted_parameters().drop(columns="fit_seconds"),
                                  b.fitted_parameters().drop(columns="fit_seconds"))


@pytest.mark.parametrize("function", ["fit_monthly_garch", "fit_monthly_dcc"])
def test_optimizer_failure_is_explicit(monkeypatch, function):
    result = SimpleNamespace(success=False, fun=1, x=np.array([0.02, 0.95]),
                             message="forced failure", nit=1)
    monkeypatch.setattr(monthly_garch, "minimize", lambda *args, **kwargs: result)
    data = monthly_data()
    with pytest.raises(ValueError, match="estimation failed"):
        if function == "fit_monthly_garch":
            monthly_garch.fit_monthly_garch([data.returns.A.to_numpy()], 60, {})
        else:
            monthly_garch.fit_monthly_dcc(data.returns, 60, 6, np.random.default_rng(0), {})


def test_calendar_and_changed_cached_input_are_rejected(monkeypatch):
    fixed_fits(monkeypatch)
    data = monthly_data()
    model = make_model(data)
    model.volatility(data)
    changed = data.returns.copy()
    changed.iloc[-1, 0] += 0.1
    with pytest.raises(ValueError, match="inputs changed"):
        model.volatility(MarketData(changed, data.meta))
    with pytest.raises(ValueError, match="complete monthly calendar"):
        make_model(data).volatility(MarketData(data.returns.drop(data.returns.index[3]), data.meta))


def test_insufficient_history_does_not_accept_a_short_monthly_fit():
    data = monthly_data()
    with pytest.raises(ValueError, match="observed months"):
        monthly_garch.fit_monthly_garch([data.returns.A.to_numpy()[:59]], 60, {})
