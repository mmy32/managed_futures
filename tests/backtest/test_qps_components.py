import json

import numpy as np
import pandas as pd
import pytest

from src.alpha_model import BlendSignal, SumReturnSignal
from src.backtest.qps_baseline import (
    build_forecasts,
    build_risk_model,
    build_signal,
    configured_components,
    eligibility,
    rescaled_components,
    trend_signal,
)
from src.config import CONFIG_DIR
from src.risk_model import DccGarchRiskModel, RollingCovarianceRiskModel, ScaledRiskModel

CLASSES = ["EQ", "EQ", "FI", "FI", "FX", "FX", "COMM", "COMM"]
RISK_SETTINGS = {
    "volatility_months": 36,
    "volatility_floor_annual": 0.0,
    "correlation_shrinkage": 0.2,
    "gross_cap": 3.0,
    "portfolio_risk_ceiling": 0.10,
    "primary_band": 0.1,
    "primary_cost_bps": 5,
}
RESCALE = {"window": 12, "minimum": 6}


def data():
    rng = np.random.default_rng(7)
    index = pd.period_range("1995-01", periods=100, freq="M")
    common = rng.normal(0, 0.02, 100)
    returns = pd.DataFrame(
        common[:, None] + rng.normal(0.001, 0.015, (100, 8)), index=index, columns=list("ABCDEFGH")
    )
    meta = pd.DataFrame({"AssetClass": CLASSES}, index=returns.columns)
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
    return returns, meta, base


def daily_returns_for(returns):
    rng = np.random.default_rng(5)
    index = pd.bdate_range("1994-12-01", "2003-12-31")
    return pd.DataFrame(
        rng.normal(0, 0.008, (len(index), returns.shape[1])), index=index, columns=returns.columns
    )


def rules():
    return json.loads((CONFIG_DIR / "risk_config.json").read_text())["trend_signal_by_asset_class"]


def with_rules(rule_map, **extra):
    return {**RISK_SETTINGS, "trend_signal_by_asset_class": rule_map, **extra}


def test_configured_rules_in_every_class_reproduce_the_default_targets():
    returns, meta, base = data()
    same = {cls: {"type": "sum", "lookback": 12} for cls in ("COMM", "EQ", "FI", "FX")}
    expected, _, _ = build_forecasts(returns, meta, base, RISK_SETTINGS)
    actual, _, _ = build_forecasts(returns, meta, base, with_rules(same))
    for name in ("trend", "static"):
        pd.testing.assert_frame_equal(actual[name], expected[name])


def test_each_market_follows_the_signal_of_its_asset_class():
    returns, meta, _ = data()
    forecast = trend_signal(rules(), meta).forecast(returns)
    by_class = {
        "EQ": SumReturnSignal(12),
        "FX": BlendSignal([SumReturnSignal(3), SumReturnSignal(12)]),
        "FI": SumReturnSignal(12),
        "COMM": SumReturnSignal(12),
    }
    for market, cls in zip(returns.columns, CLASSES, strict=True):
        expected = by_class[cls].forecast(returns[[market]])[market]
        pd.testing.assert_series_equal(forecast[market], expected, check_names=False)


def test_configured_rules_build_targets_for_trend_and_matched_static():
    returns, meta, base = data()
    targets, _, diagnostics = build_forecasts(returns, meta, base, with_rules(rules()))
    assert set(targets) == {"trend", "static"}
    assert targets["trend"].shape == targets["static"].shape
    assert (targets["static"] >= 0).all().all()  # always long
    assert set(diagnostics.strategy) == {"trend", "static"}


def test_rules_must_cover_exactly_the_asset_classes():
    _, meta, _ = data()
    incomplete = {k: v for k, v in rules().items() if k != "FX"}
    with pytest.raises(ValueError, match="asset classes"):
        trend_signal(incomplete, meta)
    with pytest.raises(ValueError, match="asset classes"):
        trend_signal({**rules(), "CRYPTO": {"type": "sum", "lookback": 12}}, meta)


def test_unknown_signal_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown signal type"):
        build_signal({"type": "momentum", "lookback": 12})


def test_eligibility_is_the_same_when_every_class_uses_the_default_rule():
    returns, meta, base = data()
    same = {cls: {"type": "sum", "lookback": 12} for cls in ("COMM", "EQ", "FI", "FX")}
    pd.testing.assert_frame_equal(
        eligibility(returns, meta, base, with_rules(same)),
        eligibility(returns, meta, base, RISK_SETTINGS),
    )


def test_blend_rule_averages_its_components():
    returns, _, _ = data()
    blend = build_signal(
        {
            "type": "blend",
            "components": [{"type": "sum", "lookback": 3}, {"type": "sum", "lookback": 12}],
        }
    )
    expected = (SumReturnSignal(3).forecast(returns) + SumReturnSignal(12).forecast(returns)) / 2
    pd.testing.assert_frame_equal(blend.forecast(returns), expected)


def test_risk_model_defaults_to_the_rolling_covariance():
    _, meta, base = data()
    model = build_risk_model(base, RISK_SETTINGS, meta)
    assert isinstance(model, RollingCovarianceRiskModel)


def test_dcc_garch_is_built_from_config_with_its_own_shrinkage():
    returns, meta, base = data()
    settings = {**RISK_SETTINGS, "risk_model": {"type": "dcc_garch", "correlation_shrinkage": 0.1}}
    model = build_risk_model(base, settings, meta, daily=daily_returns_for(returns))
    assert isinstance(model, DccGarchRiskModel)
    assert model.correlation_shrinkage == 0.1


def test_dcc_garch_needs_daily_returns_and_the_correlated_model():
    returns, meta, base = data()
    settings = {**RISK_SETTINGS, "risk_model": {"type": "dcc_garch", "correlation_shrinkage": 0.1}}
    with pytest.raises(ValueError, match="daily returns"):
        build_risk_model(base, settings, meta)
    with pytest.raises(ValueError, match="correlated"):
        build_risk_model(base, settings, meta, "diagonal", daily_returns_for(returns))


def test_unknown_risk_model_type_is_rejected():
    _, meta, base = data()
    with pytest.raises(ValueError, match="Unknown risk model type"):
        build_risk_model(base, {**RISK_SETTINGS, "risk_model": {"type": "garch"}}, meta)


def test_rescale_is_applied_only_when_configured():
    returns, meta, base = data()
    parts = configured_components(base, RISK_SETTINGS, meta)
    same = rescaled_components(parts, returns, meta, base, RISK_SETTINGS, None, None)
    assert same is parts


def test_configured_rescale_wraps_the_risk_model_with_a_past_only_scale():
    returns, meta, base = data()
    settings = {**RISK_SETTINGS, "risk_model": {"type": "rolling", "rescale": RESCALE}}
    parts = configured_components(base, settings, meta)
    source = pd.DataFrame({a: a for a in returns}, index=returns.index)
    known = pd.Series(returns.index.map(lambda month: (month - 2).end_time), index=returns.index)
    scaled = rescaled_components(parts, returns, meta, base, settings, source, known)
    assert isinstance(scaled.risk_model, ScaledRiskModel)
    assert scaled.risk_model.model is parts.risk_model
    first = returns.loc[base["start"] :].index[0]
    assert scaled.risk_model.scale.loc[first] == 1.0  # no past ratios yet
    assert scaled.risk_model.scale.loc[base["end"]] != 1.0
