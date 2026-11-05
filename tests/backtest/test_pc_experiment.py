import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("cvxpy")

from src.backtest.engine import simulate
from src.backtest.pc_experiment import (
    CommonRiskPolicy, ScheduledPolicy, common_risk_targets, policies, select_policy,
    selection_schedule, validate_specification,
)
from src.backtest.qps_baseline import build_forecasts, portfolio_limits
from src.backtest.qps_baseline import configured_components, forecasts_from, rescaled_components
from src.data_processing.strategy_inputs import select_source
from src.transaction_cost_model import LinearBpsCost
from src.portfolio_construction.trade.cost_aware import CostAwarePolicy
from tests.backtest.test_lookahead import setup


def spec():
    settings = json.loads(Path("config/pc_experiment.json").read_text())
    settings.update(selection_minimum_months=12, selection_validation_months=6,
                    selection_block_months=3, gamma_grid=[5, 10])
    return settings


def pipeline(raw, fallback, meta, base, risk):
    returns = raw.copy()
    returns["RL"], chosen, schedule = select_source(returns.RL, fallback, returns.index, 36, 2)
    source = pd.DataFrame({a: a for a in returns}, index=returns.index)
    source.RL = chosen
    known = pd.Series(pd.to_datetime(schedule.source_known_at).to_numpy(), index=returns.index)
    targets, covariance, _ = build_forecasts(returns, meta, base, risk)
    sample = returns.loc[targets["trend"].index]
    settings, limits = spec(), portfolio_limits(risk)
    ledgers, exposures = {}, {}
    policy_set = policies(covariance, limits, settings)
    for name, policy in policy_set.items():
        details = {}
        ledgers[name], _ = simulate(
            sample, targets["trend"], LinearBpsCost(1.5), source.loc[sample.index],
            liquidate=False, position_policy=policy, source_known_at=known.loc[sample.index],
            instrument_details=details,
        )
        exposures[name] = details["exposure"]
    selection, trail = selection_schedule(ledgers, settings)
    details = {}
    ledgers["walkforward"], _ = simulate(
        sample, targets["trend"], LinearBpsCost(1.5), source.loc[sample.index], liquidate=False,
        position_policy=ScheduledPolicy(policies(covariance, limits, settings), selection),
        source_known_at=known.loc[sample.index], instrument_details=details,
    )
    exposures["walkforward"] = details["exposure"]
    return ledgers, exposures, selection, covariance, sample, source.loc[sample.index]


def test_entire_optimizer_and_selection_path_is_past_only():
    raw, fallback, meta, base, risk = setup()
    base["information_lag_months"] = 2
    original = pipeline(raw, fallback, meta, base, risk)
    cutoff = pd.Period("2001-07", "M")
    changed, changed_fallback = raw.copy(), fallback.copy()
    changed.loc[cutoff:] = 0.013 - changed.loc[cutoff:] * 0.7
    changed_fallback.loc[cutoff:] = 0.02 - changed_fallback.loc[cutoff:]
    altered = pipeline(changed, changed_fallback, meta, base, risk)
    pd.testing.assert_series_equal(original[2].loc[:cutoff], altered[2].loc[:cutoff])
    for name in original[0]:
        pd.testing.assert_frame_equal(original[1][name].loc[:cutoff], altered[1][name].loc[:cutoff])
        columns = ["net_return", "cost", "turnover", "nav_end"]
        pd.testing.assert_frame_equal(original[0][name].loc[:cutoff - 1, columns],
                                      altered[0][name].loc[:cutoff - 1, columns])


def test_prefix_and_executed_holdings_replay_match_without_future_data():
    raw, fallback, meta, base, risk = setup()
    full = pipeline(raw, fallback, meta, base, risk)
    cutoff = pd.Period("2001-09", "M")
    shortened = dict(base, end=str(cutoff))
    prefix = pipeline(raw.loc[:cutoff], fallback.loc[:cutoff], meta, shortened, risk)
    for name in full[0]:
        pd.testing.assert_frame_equal(full[1][name].loc[:cutoff], prefix[1][name])
        replay, _ = simulate(full[4], full[1][name], LinearBpsCost(1.5), full[5], liquidate=False)
        for field in ["net_return", "turnover", "cost", "nav_end"]:
            np.testing.assert_allclose(full[0][name][field], replay[field], atol=1e-12)


def shadow_ledgers():
    index = pd.period_range("2000-01", periods=24, freq="M")
    baseline = pd.DataFrame(dict(net_return=0.0, liquidation_cost=0.0,
                                 rebalance_turnover=1.0), index=index)
    return {"band10": baseline, "gamma5": baseline.assign(net_return=0.01),
            "gamma10": baseline.assign(net_return=0.005)}


def test_selection_uses_prior_months_and_excludes_terminal_fee():
    ledgers = shadow_ledgers()
    chosen, scores = select_policy(ledgers, spec(), 12)
    assert chosen == "gamma5"
    assert scores[0]["information_through"] == "2000-12"
    ledgers["gamma10"].loc["2001-01":, "net_return"] = 10
    assert select_policy(ledgers, spec(), 12)[0] == chosen
    ledgers["gamma5"].loc["2000-12", "net_return"] -= 0.5
    ledgers["gamma5"].loc["2000-12", "liquidation_cost"] += 0.5
    assert select_policy(ledgers, spec(), 12)[0] == chosen
    assert select_policy(ledgers, spec(), 11)[0] == "band10"


def test_selection_ties_and_no_improvement_keep_declared_rules():
    ledgers = shadow_ledgers()
    ledgers["gamma10"]["net_return"] = 0.01
    ledgers["gamma10"]["rebalance_turnover"] = 0.5
    assert select_policy(ledgers, spec(), 12)[0] == "gamma10"
    ledgers["gamma5"]["net_return"] = -0.01
    ledgers["gamma10"]["net_return"] = 0
    assert select_policy(ledgers, spec(), 12)[0] == "band10"


def test_scheduled_policy_receives_actual_carried_holdings_across_switch():
    index = pd.period_range("2000-01", periods=3, freq="M")
    seen = []

    def first(month, previous, target, cost, switched, roll_charge=None):
        return np.array([0.5]), {}

    def second(month, previous, target, cost, switched, roll_charge=None):
        seen.append(previous.copy())
        return previous, {}

    schedule = pd.Series(["a", "b", "b"], index=index)
    returns = pd.DataFrame([0.1, -0.1, 0.02], index=index, columns=["A"])
    simulate(returns, returns * 0 + 0.5, LinearBpsCost(1.5), liquidate=False,
             position_policy=ScheduledPolicy({"a": first, "b": second}, schedule))
    assert seen[0][0] == pytest.approx(0.55 / (1 + 0.05 - 0.00015 * 0.5))


def test_common_risk_replay_matches_after_fees_including_flat_month():
    index = pd.period_range("2000-01", periods=3, freq="M")
    first = pd.DataFrame([[0.4, 0.1], [0.3, -0.2], [0, 0]], index=index)
    second = pd.DataFrame([[0.2, 0.3], [0.1, -0.3], [0.1, 0.2]], index=index)
    covariance = {t: np.diag([0.04, 0.09]) for t in index}
    targets, risk = common_risk_targets(first, second, covariance)
    for target in targets:
        ledger, _ = simulate(
            first * 0 + 0.01, target, LinearBpsCost(1.5),
            position_policy=CommonRiskPolicy(covariance, 3, risk),
        )
        np.testing.assert_allclose(ledger.forecast_after_cost, risk, atol=1e-10)
        np.testing.assert_allclose(ledger.cost, ledger.turnover * 0.00015, atol=1e-12)


@pytest.mark.parametrize("field,value", [("gamma_grid", [5, 5]), ("cost_bps", float("nan")),
                                          ("selection_validation_months", 15),
                                          ("comparison_family_size", 1)])
def test_bad_experiment_configuration_rejected(field, value):
    settings = copy.deepcopy(spec())
    settings[field] = value
    with pytest.raises(ValueError):
        validate_specification(settings)


def test_configured_dcc_rescale_and_optimizer_ignore_unavailable_daily_data():
    from tests.risk_model.test_new_models import daily_frame, monthly_data

    data = monthly_data(months=64)
    daily = daily_frame(list(data.returns.columns), end="2005-04-30")
    base = dict(start="2003-03", end="2005-04", signal_months=12, information_lag_months=2,
                instrument_volatility_scale=0.4, minimum_instruments=2, exclude_from_strategy={})
    risk = dict(volatility_months=36, volatility_floor_annual=0.02, correlation_shrinkage=0.5,
                gross_cap=3, portfolio_risk_ceiling=0.1, primary_cost_bps=1.5, primary_band=0.1,
                risk_model=dict(type="dcc_garch", correlation_shrinkage=0.1,
                                rescale=dict(window=12, minimum=6)))
    source = pd.DataFrame({a: a for a in data.returns}, index=data.returns.index)
    known = pd.Series([(t - 2).end_time for t in data.returns.index], index=data.returns.index)

    def run(observations):
        parts = configured_components(base, risk, data.meta, daily=observations)
        parts = rescaled_components(parts, data.returns, data.meta, base, risk, source, known)
        targets, covariance, _ = forecasts_from(parts, data.returns, data.meta, base)
        sample = data.returns.loc[targets["trend"].index]
        details = {}
        ledger, _ = simulate(sample, targets["trend"], LinearBpsCost(1.5), source.loc[sample.index],
                             source_known_at=known.loc[sample.index], liquidate=False,
                             position_policy=CostAwarePolicy(covariance, portfolio_limits(risk), 10),
                             instrument_details=details)
        return ledger, details["exposure"]

    original = run(daily)
    changed = daily.copy()
    changed.loc["2004-12-01":] = 0.01 - changed.loc["2004-12-01":] * 4
    altered = run(changed)
    # January's risk cutoff is November; monthly realized returns/held-position drift are identical.
    pd.testing.assert_frame_equal(original[1].loc[:"2005-01"], altered[1].loc[:"2005-01"])
    pd.testing.assert_series_equal(original[0].net_return.loc[:"2005-01"],
                                   altered[0].net_return.loc[:"2005-01"])
