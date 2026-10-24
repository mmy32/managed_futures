import json

import numpy as np
import pandas as pd
import pytest

from src.alpha_model import BlendSignal, SumReturnSignal
from src.backtest.qps_baseline import build_forecasts, eligibility
from src.backtest.qps_v2 import build_forecasts_v2, build_signal, eligibility_v2, trend_signal
from src.config import CONFIG_DIR

CLASSES = ["EQ", "EQ", "FI", "FI", "FX", "FX", "COMM", "COMM"]
RISK_SETTINGS = {
    "volatility_months": 36,
    "volatility_floor_annual": 0.0,
    "correlation_shrinkage": 0.2,
    "gross_cap": 3.0,
    "portfolio_risk_ceiling": 0.10,
}


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


def rules():
    return json.loads((CONFIG_DIR / "qps_v2.json").read_text())["trend_signal_by_asset_class"]


def test_same_rule_in_every_class_reproduces_the_baseline_targets():
    returns, meta, base = data()
    same = {cls: {"type": "sum", "lookback": 12} for cls in ("COMM", "EQ", "FI", "FX")}
    expected, _, _ = build_forecasts(returns, meta, base, RISK_SETTINGS)
    actual, _, _ = build_forecasts_v2(returns, meta, base, RISK_SETTINGS, same)
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
    targets, _, diagnostics = build_forecasts_v2(returns, meta, base, RISK_SETTINGS, rules())
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


def test_eligibility_matches_the_baseline_when_every_class_uses_the_baseline_rule():
    returns, meta, base = data()
    same = {cls: {"type": "sum", "lookback": 12} for cls in ("COMM", "EQ", "FI", "FX")}
    pd.testing.assert_frame_equal(
        eligibility_v2(returns, meta, base, RISK_SETTINGS, same),
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
