import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.backtest.qps_baseline import build_forecasts, portfolio_limits
from src.portfolio_construction import BandPolicy, PortfolioLimits, band_positions, enforce_limits
from src.risk_model import portfolio_risk
from src.transaction_cost_model import LinearBpsCost
from tests.risk_model.test_risk_model import data, settings


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
    w, scale = enforce_limits(
        proposed, previous, covariance, LinearBpsCost(10), switched, PortfolioLimits(3, 0.10)
    )
    # With both sources switched, fee=.001*(3*scale+3); solve 3s/(1-fee)=3.
    expected = (1 - 0.003) / (1 + 0.003)
    assert scale == pytest.approx(expected)
    assert np.abs(w).sum() / (1 - 0.001 * (np.abs(w).sum() + 3)) == pytest.approx(3)


def test_risk_limit_overrides_an_inside_band_position():
    month = pd.Period("2000-01", "M")
    cov = np.array([[0.04]])
    policy = BandPolicy({month: cov}, portfolio_limits(settings()), 0.20)
    w, d = policy(month, np.array([0.55]), np.array([0.5]), LinearBpsCost(10), np.array([False]))
    assert d["band_skipped_resizes"] == 1
    assert d["net_skipped_resizes"] == 0
    assert d["risk_override"]
    assert w[0] < 0.5
    assert d["forecast_after_cost"] == pytest.approx(0.1)


def test_band_accounting_matches_replay_of_executed_positions():
    r, m, b = data()
    cfg = settings()
    targets, cov, _ = build_forecasts(r, m, b, cfg)
    sample = r.loc[b["start"] : b["end"]]
    policy = BandPolicy(cov, portfolio_limits(cfg), 0.10)
    l, _ = simulate(sample, targets["trend"], LinearBpsCost(5), position_policy=policy)
    executed = pd.DataFrame.from_dict(policy.executed, orient="index", columns=r.columns)
    replay, _ = simulate(sample, executed, LinearBpsCost(5))
    for col in ["net_return", "turnover", "cost", "nav_end"]:
        np.testing.assert_allclose(l[col], replay[col], atol=1e-14)
    assert l.gross_after_cost.max() <= 3 + 1e-10
    assert l.forecast_after_cost.max() <= 0.10 + 1e-10


def test_holding_inside_band_has_zero_rebalance_turnover():
    index = pd.period_range("2000-01", periods=2, freq="M")
    r = pd.DataFrame([0.01, 0.02], index=index, columns=["A"])
    t = pd.DataFrame([0.1, 0.1], index=index, columns=["A"])
    cov = {month: np.array([[0.01]]) for month in index}
    policy = BandPolicy(cov, portfolio_limits(settings()), 0.1)
    l, _ = simulate(r, t, LinearBpsCost(0), liquidate=False, position_policy=policy)
    assert l.rebalance_turnover.iloc[0] == 0.1
    assert l.rebalance_turnover.iloc[1] == 0
    assert policy.executed[index[1]][0] == pytest.approx(0.101 / 1.001)


def test_risk_cap_prevents_high_exposure_for_low_volatility_assets():
    proposed = np.array([30.0, -20.0])
    previous = np.zeros(2)
    cov = np.eye(2) * 0.02**2
    w, _ = enforce_limits(
        proposed, previous, cov, LinearBpsCost(5), np.zeros(2, dtype=bool), PortfolioLimits(3, 0.1)
    )
    fee = 0.0005 * np.abs(w).sum()
    assert np.abs(w).sum() / (1 - fee) == pytest.approx(3)
    assert portfolio_risk(w, cov) / (1 - fee) <= 0.1
