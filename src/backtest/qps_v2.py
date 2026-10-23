"""qps v2: the qps baseline with the trend signal chosen per asset class.

Everything except the trend signal is the baseline's: risk model, sizing, limits and timing.
The STATIC benchmark keeps the same eligibility as the trend signal, so the comparison stays matched.
"""

from dataclasses import replace

from src.alpha_model import (
    AlwaysLongLike,
    AssetClassSignal,
    Signal,
    SkipMonthSignal,
    SumReturnSignal,
)
from src.backtest.qps_baseline import QpsComponents, forecasts_from, qps_components
from src.config import ASSET_CLASSES

SIGNAL_TYPES = {"sum": SumReturnSignal, "skip_month": SkipMonthSignal}


def build_signal(rule: dict) -> Signal:
    """One signal from a rule such as {"type": "skip_month", "lookback": 12, "skip": 1}."""
    options = dict(rule)
    kind = options.pop("type", None)
    if kind not in SIGNAL_TYPES:
        raise ValueError(f"Unknown signal type {kind!r}; choose from {sorted(SIGNAL_TYPES)}")
    return SIGNAL_TYPES[kind](**options)


def trend_signal(rules: dict[str, dict], meta) -> AssetClassSignal:
    """Route each market to its asset class's rule. Every asset class needs exactly one rule."""
    if set(rules) != ASSET_CLASSES:
        raise ValueError(f"Rules must cover exactly the asset classes {sorted(ASSET_CLASSES)}")
    return AssetClassSignal(
        {cls: build_signal(rule) for cls, rule in rules.items()}, meta.AssetClass
    )


def qps_v2_components(base, settings, rules, meta, model="correlated") -> QpsComponents:
    """base: baseline_config.json; settings: risk_config.json; rules: qps_v2.json trend rules."""
    trend = trend_signal(rules, meta)
    return replace(
        qps_components(base, settings, model),
        signals={"trend": trend, "static": AlwaysLongLike(trend)},
    )


def build_forecasts_v2(returns, meta, base, settings, rules, model="correlated"):
    """Return (targets by strategy, covariance by month, diagnostics)."""
    parts = qps_v2_components(base, settings, rules, meta, model)
    return forecasts_from(parts, returns, meta, base, model)
