import numpy as np
import pandas as pd
import pytest

from src.backtest.qps_baseline import build_forecasts
from src.risk_model import portfolio_risk


def settings():
    return {
        "volatility_months": 36,
        "volatility_floor_annual": 0.02,
        "portfolio_risk_ceiling": 0.10,
        "gross_cap": 3.0,
        "correlation_shrinkage": 0.5,
    }


def data():
    rng = np.random.default_rng(124)
    index = pd.period_range("1995-01", periods=100, freq="M")
    common = rng.normal(0, 0.02, 100)
    r = pd.DataFrame(
        common[:, None] + rng.normal(0.001, 0.015, (100, 8)), index=index, columns=list("ABCDEFGH")
    )
    meta = pd.DataFrame(
        {"AssetClass": ["EQ", "EQ", "FI", "FI", "FX", "FX", "COMM", "COMM"]}, index=r.columns
    )
    base = {
        "start": "2000-01",
        "end": "2002-12",
        "signal_months": 12,
        "volatility_months": 36,
        "information_lag_months": 1,
        "volatility_floor_annual": 0.0,
        "instrument_volatility_scale": 0.4,
        "minimum_instruments": 2,
        "exclude_from_strategy": {},
    }
    return r, meta, base


def test_covariance_accounts_for_hedging_and_is_positive_definite():
    r, m, b = data()
    targets, cov, _diag = build_forecasts(r, m, b, settings())
    month = targets["trend"].index[0]
    matrix = cov[month]
    assert np.linalg.eigvalsh(matrix).min() > 0
    long = np.zeros(8)
    long[:2] = [0.2, 0.2]
    hedge = np.zeros(8)
    hedge[:2] = [0.2, -0.2]
    assert portfolio_risk(long, matrix) > portfolio_risk(hedge, matrix)
    # Forecast variances include the explicit 2% floor.
    assert (np.diag(matrix) >= 0.02**2 - 1e-12).all()


@pytest.mark.parametrize("model", ["diagonal", "correlated", "class_balanced"])
def test_current_and_future_returns_do_not_change_current_forecast(model):
    r, m, b = data()
    cfg = settings()
    month = pd.Period("2001-06", "M")
    targets, cov, _ = build_forecasts(r, m, b, cfg, model)
    modified = r.copy()
    modified.loc[month:, "A"] = 100
    modified.loc[month:, "B"] = np.nan
    altered, cov2, _ = build_forecasts(modified, m, b, cfg, model)
    for strategy in targets:
        pd.testing.assert_frame_equal(targets[strategy].loc[:month], altered[strategy].loc[:month])
    for t in targets["trend"].loc[:month].index:
        np.testing.assert_allclose(cov[t], cov2[t])


def test_incomplete_past_window_removes_asset_without_pairwise_filling():
    r, m, b = data()
    r.loc["1999-12", "A"] = np.nan
    targets, cov, _ = build_forecasts(r, m, b, settings())
    assert targets["static"].loc["2000-01", "A"] == 0
    assert (cov[pd.Period("2000-01", "M")][0] == 0).all()
    assert targets["static"].loc["2000-01", "B"] > 0


def test_class_balance_means_equal_standalone_risk_before_bands():
    r, m, b = data()
    targets, cov, _ = build_forecasts(r, m, b, settings(), "class_balanced")
    for strategy in targets:
        month = targets[strategy].index[-1]
        w = targets[strategy].loc[month].to_numpy()
        risks = []
        for group in ["EQ", "FI", "FX", "COMM"]:
            risks.append(portfolio_risk(np.where(m.AssetClass.eq(group), w, 0), cov[month]))
        np.testing.assert_allclose(risks, np.repeat(risks[0], 4), rtol=1e-10)


def test_shrinkage_stabilizes_more_instruments_than_observations():
    rng = np.random.default_rng(44)
    r, m, b = data()
    r = pd.DataFrame(
        rng.normal(0, 0.02, (len(r), 45)), index=r.index, columns=[f"A{i}" for i in range(45)]
    )
    m = pd.DataFrame({"AssetClass": "EQ"}, index=r.columns)
    targets, cov, _ = build_forecasts(r, m, b, settings())
    month = targets["trend"].index[0]
    assert np.linalg.eigvalsh(cov[month]).min() > 0
    past = r.loc[: month - 1].tail(36)
    assert np.linalg.matrix_rank(past.cov()) < 45


def test_volatility_floor_is_used_in_forecast_as_well_as_sizing():
    r, m, b = data()
    r["A"] *= 0.0001
    targets, cov, _ = build_forecasts(r, m, b, settings())
    month = targets["trend"].index[0]
    assert cov[month][0, 0] == pytest.approx(0.02**2)
