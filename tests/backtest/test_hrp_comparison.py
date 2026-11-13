import copy

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.backtest.hrp_comparison import comparison_components, load_comparison, validate_comparison
from src.backtest.qps_baseline import configured_components, forecasts_from, rescaled_components
from src.portfolio_construction import BandPolicy
from src.portfolio_construction.hold import HrpSizing
from src.risk_model import ScaledRiskModel
from src.transaction_cost_model import LinearBpsCost
from tests.backtest.test_qps_components import RESCALE, RISK_SETTINGS, data


def comparison_inputs():
    spec, _, _ = load_comparison()
    returns, meta, base = data()
    # The shared upstream configuration currently defaults to HRP. The comparison
    # must override that default when building its baseline and shadow portfolio.
    base["hold_sizing"] = "hrp_within_class"
    risk = {
        **RISK_SETTINGS,
        "primary_cost_bps": 2,
        "risk_model": {"type": "rolling", "rescale": RESCALE},
    }
    source = pd.DataFrame({name: name for name in returns}, index=returns.index)
    known = pd.Series(returns.index.map(lambda month: (month - 2).end_time), index=returns.index)
    return spec, base, risk, returns, meta, source, known


def test_named_comparison_uses_one_baseline_shadow_and_shared_forecasts():
    spec, base, risk, returns, meta, source, known = comparison_inputs()
    original_base, original_risk = copy.deepcopy(base), copy.deepcopy(risk)
    shared, cases = comparison_components(spec, base, risk, returns, meta, source, known)
    baseline, enhanced = cases["baseline"], cases["enhanced"]

    assert base == original_base and risk == original_risk
    assert shared["hold_sizing"] == "inverse_vol"
    assert baseline.adjustment is None and isinstance(enhanced.adjustment, HrpSizing)
    assert baseline.risk_model is enhanced.risk_model
    assert baseline.signals is enhanced.signals and baseline.sizer is enhanced.sizer
    assert baseline.limits == enhanced.limits
    assert isinstance(baseline.risk_model, ScaledRiskModel)

    # Independently construct the inverse-volatility shadow and verify its scale.
    shadow = configured_components(shared, risk, meta)
    shadow = rescaled_components(shadow, returns, meta, shared, risk, source, known)
    pd.testing.assert_series_equal(baseline.risk_model.scale, shadow.risk_model.scale)

    base_targets, base_cov, _ = forecasts_from(baseline, returns, meta, shared)
    hrp_targets, hrp_cov, _ = forecasts_from(enhanced, returns, meta, shared)
    assert base_targets["trend"].index.equals(hrp_targets["trend"].index)
    assert not np.allclose(base_targets["trend"].to_numpy(), hrp_targets["trend"].to_numpy())
    for month in base_cov:
        np.testing.assert_allclose(base_cov[month], hrp_cov[month])

    # Both paths must use the same dates, band, cost and source schedule.
    sample = returns.loc[shared["start"] : shared["end"]]
    details, ledgers = {}, {}
    for name, targets, covariance, parts in (
        ("baseline", base_targets, base_cov, baseline),
        ("enhanced", hrp_targets, hrp_cov, enhanced),
    ):
        details[name] = {}
        ledgers[name], _ = simulate(
            sample,
            targets["trend"],
            LinearBpsCost(risk["primary_cost_bps"]),
            source.loc[sample.index],
            source_known_at=known.loc[sample.index],
            position_policy=BandPolicy(covariance, parts.limits, risk["primary_band"]),
            instrument_details=details[name],
        )
        ledger = ledgers[name]
        np.testing.assert_allclose(ledger.cost, ledger.turnover * risk["primary_cost_bps"] / 10000)
        np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost)
        assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
    assert ledgers["baseline"].index.equals(ledgers["enhanced"].index)
    assert not np.allclose(details["baseline"]["exposure"], details["enhanced"]["exposure"])


@pytest.mark.parametrize(
    "change",
    [
        {"rescale_shadow": "enhanced"},
        {"strategy": "static"},
        {"portfolios": {"baseline": {"hold_sizing": "hrp_within_class"},
                        "enhanced": {"hold_sizing": "hrp_within_class"}}},
        {"portfolios": {"baseline": {"hold_sizing": "inverse_vol", "cost_bps": 0},
                        "enhanced": {"hold_sizing": "hrp_within_class"}}},
    ],
)
def test_comparison_rejects_nonmatching_specifications(change):
    spec, *_ = comparison_inputs()
    with pytest.raises(ValueError, match="Comparison"):
        validate_comparison({**spec, **change})


def test_comparison_stops_on_a_later_missing_held_return():
    spec, base, risk, returns, meta, source, known = comparison_inputs()
    returns.loc[base["end"]] = np.nan
    with pytest.raises(ValueError, match="Missing held return"):
        comparison_components(spec, base, risk, returns, meta, source, known)
