import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.risk_model.risk_model import (
    BandPolicy,
    band_positions,
    build_forecasts,
    enforce_limits,
    portfolio_risk,
)


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


def test_band_preserves_inside_long_and_short_and_trades_to_edge():
    previous = np.array([0.019, 0.025, 0.015, -0.019, -0.025, -0.015])
    target = np.array([0.02, 0.02, 0.02, -0.02, -0.02, -0.02])
    np.testing.assert_allclose(
        band_positions(previous, target, 0.1), [0.019, 0.022, 0.018, -0.019, -0.022, -0.018]
    )


def test_entries_exits_and_sign_changes_override_band():
    np.testing.assert_allclose(
        band_positions(np.array([0, 0.02, 0.02, -0.02]), np.array([0.02, 0, -0.02, 0.02]), 0.2),
        [0.02, 0, -0.02, 0.02],
    )


def test_zero_band_executes_exact_target():
    np.testing.assert_allclose(
        band_positions(np.array([0.1, -0.2, 0]), np.array([0.15, -0.1, 0.05]), 0),
        [0.15, -0.1, 0.05],
    )


def test_after_cost_gross_limit_includes_source_close_open():
    covariance = np.eye(2) * 0.0001
    proposed = np.array([1.5, 1.5])
    previous = proposed.copy()
    switched = np.array([True, True])
    w, scale = enforce_limits(proposed, previous, covariance, 0.001, switched, 3, 0.10)
    # With both sources switched, fee=.001*(3*scale+3); solve 3s/(1-fee)=3.
    expected = (1 - 0.003) / (1 + 0.003)
    assert scale == pytest.approx(expected)
    assert np.abs(w).sum() / (1 - 0.001 * (np.abs(w).sum() + 3)) == pytest.approx(3)


def test_risk_limit_overrides_an_inside_band_position():
    month = pd.Period("2000-01", "M")
    cov = np.array([[0.04]])
    policy = BandPolicy({month: cov}, settings(), 0.20)
    w, d = policy(month, np.array([0.55]), np.array([0.5]), 0.001, np.array([False]))
    assert d["band_skipped_resizes"] == 1
    assert d["net_skipped_resizes"] == 0
    assert d["risk_override"]
    assert w[0] < 0.5
    assert d["forecast_after_cost"] == pytest.approx(0.1)


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


def test_band_accounting_matches_replay_of_executed_positions():
    r, m, b = data()
    cfg = settings()
    targets, cov, _ = build_forecasts(r, m, b, cfg)
    sample = r.loc[b["start"] : b["end"]]
    policy = BandPolicy(cov, cfg, 0.10)
    l, _ = simulate(sample, targets["trend"], 5, position_policy=policy)
    executed = pd.DataFrame.from_dict(policy.executed, orient="index", columns=r.columns)
    replay, _ = simulate(sample, executed, 5)
    for col in ["net_return", "turnover", "cost", "nav_end"]:
        np.testing.assert_allclose(l[col], replay[col], atol=1e-14)
    assert l.gross_after_cost.max() <= 3 + 1e-10
    assert l.forecast_after_cost.max() <= 0.10 + 1e-10


def test_holding_inside_band_has_zero_rebalance_turnover():
    index = pd.period_range("2000-01", periods=2, freq="M")
    r = pd.DataFrame([0.01, 0.02], index=index, columns=["A"])
    t = pd.DataFrame([0.1, 0.1], index=index, columns=["A"])
    cov = {month: np.array([[0.01]]) for month in index}
    policy = BandPolicy(cov, settings(), 0.1)
    l, _ = simulate(r, t, 0, liquidate=False, position_policy=policy)
    assert l.rebalance_turnover.iloc[0] == 0.1
    assert l.rebalance_turnover.iloc[1] == 0
    assert policy.executed[index[1]][0] == pytest.approx(0.101 / 1.001)


def test_risk_cap_prevents_high_exposure_for_low_volatility_assets():
    proposed = np.array([30.0, -20.0])
    previous = np.zeros(2)
    cov = np.eye(2) * 0.02**2
    w, _ = enforce_limits(proposed, previous, cov, 0.0005, np.zeros(2, dtype=bool), 3, 0.1)
    fee = 0.0005 * np.abs(w).sum()
    assert np.abs(w).sum() / (1 - fee) == pytest.approx(3)
    assert portfolio_risk(w, cov) / (1 - fee) <= 0.1


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
