"""Behavioral checks for timing, missing data, funding and exposure accounting."""

import numpy as np
import pandas as pd
import pytest

from src.alpha_model import AlwaysLongSignal, SumReturnSignal, lagged
from src.backtest.engine import performance, regression_alpha, simulate
from src.models import MarketData
from src.portfolio_construction import InverseVolatilitySizer
from src.risk_model import RollingCovarianceRiskModel
from src.transaction_cost_model import LinearBpsCost


def weights_and_signals(returns, meta, config):
    """Compose the qps pieces the way the pipeline does; returns weights and their inputs."""
    lag = config["information_lag_months"]
    risk = RollingCovarianceRiskModel(
        config["volatility_months"], lag, config["volatility_floor_annual"], 0.5
    )
    sizer = InverseVolatilitySizer(
        config["instrument_volatility_scale"],
        config["volatility_floor_annual"],
        config["minimum_instruments"],
        config["exclude_from_strategy"],
    )
    vol = risk.volatility(MarketData(returns, meta))
    signal = lagged(SumReturnSignal(config["signal_months"]).forecast(returns), lag)
    always_long = lagged(AlwaysLongSignal(config["signal_months"]).forecast(returns), lag)
    trend, eligible = sizer.weights(signal, vol)
    static, _ = sizer.weights(always_long, vol)
    return {"trend": trend, "static": static, "eligible": eligible, "signal": signal, "vol": vol}


def frames(values, targets):
    index = pd.period_range("2000-01", periods=len(values), freq="M")
    return pd.DataFrame(values, index=index, columns=["A"]), pd.DataFrame(
        targets, index=index, columns=["A"]
    )


def fixture():
    rng = np.random.default_rng(33)
    r = pd.DataFrame(
        rng.normal(0.003, 0.04, (90, 3)),
        index=pd.period_range("1995-01", periods=90, freq="M"),
        columns=["A", "B", "C"],
    )
    meta = pd.DataFrame({"AssetClass": ["EQ", "FI", "FX"]}, index=r.columns)
    c = {
        "information_lag_months": 1,
        "signal_months": 12,
        "volatility_months": 36,
        "exclude_from_strategy": {},
        "start": "2000-01",
        "volatility_floor_annual": 0.0,
        "instrument_volatility_scale": 0.4,
        "minimum_instruments": 2,
    }
    return r, meta, c


def test_signal_and_risk_use_exact_prior_window():
    r, m, c = fixture()
    w = weights_and_signals(r, m, c)
    t = pd.Period("2000-01", "M")
    past = r.loc[: t - 1]
    expected_vol = past.tail(36).std(ddof=1) * np.sqrt(12)
    np.testing.assert_allclose(w["vol"].loc[t], expected_vol)
    np.testing.assert_allclose(w["signal"].loc[t], np.sign(past.tail(12).sum()))
    np.testing.assert_allclose(w["static"].loc[t], 0.4 / expected_vol / 3)
    np.testing.assert_allclose(w["trend"].loc[t].abs(), w["static"].loc[t])


@pytest.mark.parametrize("lag", [1, 2])
def test_future_prices_and_missingness_cannot_change_past_targets(lag):
    r, m, c = fixture()
    c["information_lag_months"] = lag
    t = pd.Period("2000-03", "M")
    before = weights_and_signals(r, m, c)
    changed = r.copy()
    changed.loc[t:, "A"] = 100
    changed.loc[t:, "B"] = np.nan
    after = weights_and_signals(changed, m, c)
    for k in ["trend", "static", "signal", "vol", "eligible"]:
        pd.testing.assert_frame_equal(before[k].loc[:t], after[k].loc[:t])


def test_history_gap_requires_new_complete_risk_window():
    r, m, c = fixture()
    r.loc["1999-12", "A"] = np.nan
    w = weights_and_signals(r, m, c)
    assert not w["eligible"].loc["2000-01", "A"]
    assert w["static"].loc["2000-01", "A"] == 0
    assert w["eligible"].loc["2000-01", "B"]


def test_minimum_and_exclusions():
    r, m, c = fixture()
    c["exclude_from_strategy"] = {"A": "test", "B": "test"}
    w = weights_and_signals(r, m, c)
    assert w["static"].eq(0).all().all()
    assert w["trend"].eq(0).all().all()


def test_zero_volatility_ineligible():
    r, m, c = fixture()
    r["A"] = 0
    w = weights_and_signals(r, m, c)
    assert not w["eligible"]["A"].any()
    assert np.isfinite(w["static"].to_numpy()).all()


def test_missing_held_return_fails_instead_of_filling():
    r, w = frames([0.1, np.nan], [0.5, 0.5])
    with pytest.raises(ValueError, match="Missing held return"):
        simulate(r, w, LinearBpsCost(0))
    w.iloc[1] = 0
    ledger, _ = simulate(r, w, LinearBpsCost(0))
    assert ledger.net_return.iloc[1] == 0


def test_entry_drift_rebalance_and_terminal_costs():
    r, w = frames([0.1, -0.05], [0.5, 0.5])
    l, a = simulate(r, w, LinearBpsCost(10))
    first_net = 0.5 * 0.1 - 0.001 * 0.5
    carried = 0.5 * 1.1 / (1 + first_net)
    second_trade = abs(0.5 - carried)
    final_trade = 0.5 * 0.95
    assert l.net_return.iloc[0] == pytest.approx(first_net)
    assert l.rebalance_turnover.iloc[1] == pytest.approx(second_trade)
    assert l.terminal_turnover.iloc[1] == pytest.approx(final_trade)
    assert l.net_return.iloc[1] == pytest.approx(-0.025 - 0.001 * (second_trade + final_trade))
    assert l.nav_end.iloc[-1] == pytest.approx((1 + first_net) * (1 + l.net_return.iloc[1]))
    np.testing.assert_allclose(a.sum(axis=1), l.gross_return)


def test_short_and_flip_accounting():
    r, w = frames([0.1, 0.2], [-0.5, 0.5])
    l, _ = simulate(r, w, LinearBpsCost(0), liquidate=False)
    assert l.net_return.iloc[0] == pytest.approx(-0.05)
    assert l.net_return.iloc[1] == pytest.approx(0.1)
    assert l.rebalance_turnover.iloc[1] == pytest.approx(0.5 + 0.55 / 0.95)


def test_source_switch_requires_close_and_open_even_with_no_net_trade():
    r, w = frames([0, 0], [0.5, 0.5])
    source = pd.DataFrame(["RL", "ER"], index=r.index, columns=r.columns)
    l, _ = simulate(r, w, LinearBpsCost(0), source, liquidate=False)
    assert l.rebalance_turnover.iloc[1] == 1
    assert l.source_switch_extra_turnover.iloc[1] == 1
    same = pd.DataFrame(["RL", "RL"], index=r.index, columns=r.columns)
    ordinary, _ = simulate(r, w, LinearBpsCost(0), same, liquidate=False)
    assert ordinary.rebalance_turnover.iloc[1] == 0


def test_rf_on_collateral_after_entry_cost_not_on_gross_exposure():
    r, w = frames([0.01], [2.0])
    rf = pd.Series([0.002], index=r.index)
    l, _ = simulate(r, w, LinearBpsCost(5), risk_free=rf, liquidate=False)
    assert l.collateral_income.iloc[0] == pytest.approx(0.002 * (1 - 0.001))
    assert l.net_return.iloc[0] == pytest.approx(0.02 + 0.002 * (1 - 0.001) - 0.001)


def test_flat_account_earns_rf_exactly_once():
    r, w = frames([np.nan, np.nan], [0, 0])
    rf = pd.Series([0.01, 0.01], index=r.index)
    l, _ = simulate(r, w, LinearBpsCost(10), risk_free=rf)
    np.testing.assert_allclose(l.net_return, rf)
    assert l.cost.sum() == 0


def test_initial_capital_is_in_drawdown_peak():
    r, w = frames([-0.1, 0.02], [1, 1])
    l, _ = simulate(r, w, LinearBpsCost(0))
    assert performance(l)["max_drawdown"] == pytest.approx(-0.1)


def test_insolvent_account_is_rejected():
    r, w = frames([-0.6], [2])
    with pytest.raises(ValueError, match="insolvent"):
        simulate(r, w, LinearBpsCost(0))


def test_known_regression_intercept_and_slope():
    index = pd.period_range("2000-01", periods=180, freq="M")
    x = pd.DataFrame({"benchmark": np.linspace(-0.08, 0.08, 180)}, index=index)
    y = 0.002 + 0.7 * x.benchmark
    row, _ = regression_alpha(y, x, 6)
    assert row["alpha_ann"] == pytest.approx(0.024)
    assert row["beta_benchmark"] == pytest.approx(0.7)
    assert row["alpha_ci_low_ann"] == pytest.approx(0.024)


def test_hac_interval_agrees_with_direct_sandwich_covariance():
    import statsmodels.api as sm
    from statsmodels.stats.sandwich_covariance import cov_hac

    rng = np.random.default_rng(17)
    x = pd.DataFrame({"b": rng.normal(0, 0.04, 180)})
    noise = np.zeros(180)
    for t in range(1, 180):
        noise[t] = 0.5 * noise[t - 1] + rng.normal(0, 0.01)
    y = 0.003 + 0.4 * x.b + noise
    row, _ = regression_alpha(y, x, 6)
    fit = sm.OLS(y, sm.add_constant(x)).fit()
    expected = np.sqrt(cov_hac(fit, nlags=6, use_correction=True)[0, 0]) * 12
    assert row["alpha_se_ann"] == pytest.approx(expected)
