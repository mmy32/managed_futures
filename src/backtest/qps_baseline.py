"""Compose the qps strategy from its config files: the one place settings become objects.

The trend signal per asset class and the risk model are chosen in risk_config.json. Without
`trend_signal_by_asset_class` every class uses the baseline rule (the sum of the previous
`signal_months` returns); without `risk_model` the risk model is the rolling covariance.
The hold stage is chosen by `hold_sizing` in baseline_config.json (default inverse volatility).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

import pandas as pd

from src.alpha_model import (
    AlwaysLongLike,
    AssetClassSignal,
    BlendSignal,
    Signal,
    SkipMonthSignal,
    SumReturnSignal,
    lagged,
)
from src.backtest.engine import simulate
from src.config import ASSET_CLASSES
from src.models import MarketData
from src.portfolio_construction import (
    BandPolicy,
    InverseVolatilitySizer,
    PortfolioLimits,
    construct_targets,
)
from src.portfolio_construction.hold import HrpSizing
from src.risk_model import (
    DccGarchRiskModel,
    RiskModel,
    RollingCovarianceRiskModel,
    ScaledRiskModel,
    standardized_returns,
    trailing_scale,
)
from src.transaction_cost_model import LinearBpsCost

RISK_MODELS = ("diagonal", "correlated", "class_balanced")
RISK_MODEL_TYPES = ("rolling", "dcc_garch")
SIGNAL_TYPES = {"sum": SumReturnSignal, "skip_month": SkipMonthSignal}


@dataclass(frozen=True)
class QpsComponents:
    signals: dict[str, Signal]
    risk_model: RiskModel
    sizer: InverseVolatilitySizer
    limits: PortfolioLimits
    adjustment: Callable | None = None


def hold_adjustment(name: str) -> Callable | None:
    """The hold-stage reshaping named by `hold_sizing`: None keeps inverse-volatility sizes."""
    if name == "inverse_vol":
        return None
    if name == "hrp_within_class":
        return HrpSizing(within_class=True, signed=True)
    raise ValueError(f"Unknown hold_sizing {name!r}")


def portfolio_limits(settings) -> PortfolioLimits:
    return PortfolioLimits(settings["gross_cap"], settings["portfolio_risk_ceiling"])


def build_signal(rule: dict) -> Signal:
    """One signal from a rule such as {"type": "skip_month", "lookback": 12, "skip": 1}.

    A blend takes {"type": "blend", "components": [rule, rule, ...]}.
    """
    options = dict(rule)
    kind = options.pop("type", None)
    if kind == "blend":
        return BlendSignal([build_signal(part) for part in options["components"]])
    if kind not in SIGNAL_TYPES:
        raise ValueError(
            f"Unknown signal type {kind!r}; choose from {sorted([*SIGNAL_TYPES, 'blend'])}"
        )
    return SIGNAL_TYPES[kind](**options)


def trend_rules(base, settings) -> dict[str, dict]:
    """Trend rule per asset class: the configured rules, else the baseline rule in every class."""
    default = {cls: {"type": "sum", "lookback": base["signal_months"]} for cls in ASSET_CLASSES}
    return settings.get("trend_signal_by_asset_class", default)


def trend_signal(rules: dict[str, dict], meta) -> AssetClassSignal:
    """Route each market to its asset class's rule. Every asset class needs exactly one rule."""
    if set(rules) != ASSET_CLASSES:
        raise ValueError(f"Rules must cover exactly the asset classes {sorted(ASSET_CLASSES)}")
    return AssetClassSignal(
        {cls: build_signal(rule) for cls, rule in rules.items()}, meta.AssetClass
    )


def build_risk_model(base, settings, meta, model="correlated", daily=None) -> RiskModel:
    """The configured risk model. `daily` (daily returns by market) is needed by dcc_garch."""
    if model not in RISK_MODELS:
        raise ValueError("Unknown risk model")
    options = settings.get("risk_model", {"type": "rolling"})
    kind = options["type"]
    if kind not in RISK_MODEL_TYPES:
        raise ValueError(f"Unknown risk model type {kind!r}; choose from {list(RISK_MODEL_TYPES)}")
    common = {
        "window": settings["volatility_months"],
        "lag": base["information_lag_months"],
        "volatility_floor": settings["volatility_floor_annual"],
    }
    if kind == "rolling":
        return RollingCovarianceRiskModel(
            **common,
            correlation_shrinkage=settings["correlation_shrinkage"],
            diagonal=model == "diagonal",
        )
    if model != "correlated":
        raise ValueError("dcc_garch supports only the correlated risk model")
    if daily is None:
        raise ValueError("dcc_garch needs daily returns")
    return DccGarchRiskModel(
        daily,
        meta.AssetClass,
        **common,
        correlation_shrinkage=options["correlation_shrinkage"],
        forecast_start=base.get("risk_forecast_start"),
    )


def qps_components(base, settings, meta, risk_model, model="correlated") -> QpsComponents:
    """base: baseline_config.json; settings: risk_config.json; risk_model from build_risk_model."""
    if model not in RISK_MODELS:
        raise ValueError("Unknown risk model")
    floor = settings["volatility_floor_annual"]
    trend = trend_signal(trend_rules(base, settings), meta)
    return QpsComponents(
        signals={"trend": trend, "static": AlwaysLongLike(trend)},
        risk_model=risk_model,
        sizer=InverseVolatilitySizer(
            scale=base["instrument_volatility_scale"],
            volatility_floor=floor,
            minimum_instruments=base["minimum_instruments"],
            excluded=base["exclude_from_strategy"],
        ),
        limits=portfolio_limits(settings),
        adjustment=hold_adjustment(base.get("hold_sizing", "inverse_vol")),
    )


def configured_components(base, settings, meta, model="correlated", daily=None) -> QpsComponents:
    """Components with the risk model chosen in `settings`, before any rescale."""
    risk_model = build_risk_model(base, settings, meta, model, daily)
    return qps_components(base, settings, meta, risk_model, model)


def rescaled_components(
    parts: QpsComponents, returns, meta, base, settings, source, known, model="correlated"
) -> QpsComponents:
    """Scale the risk model's covariance by its own past realised/forecast ratio (config `rescale`).

    The trend strategy is run once with the unscaled model; its standardized returns through
    the configured information cutoff give one scale per month. A configuration without
    `rescale` returns `parts` unchanged. A missing held return stops the run: it must never
    cause the rescale to be dropped retrospectively from the entire history.
    """
    options = settings.get("risk_model", {}).get("rescale")
    if options is None:
        return parts
    targets, covariance, _ = forecasts_from(parts, returns, meta, base, model)
    sample = returns.loc[base["start"] : base["end"]]
    ledger, _ = simulate(
        sample,
        targets["trend"],
        LinearBpsCost(settings["primary_cost_bps"]),
        source.loc[sample.index],
        position_policy=BandPolicy(covariance, parts.limits, settings["primary_band"]),
        source_known_at=known.loc[sample.index],
    )
    scale = trailing_scale(
        standardized_returns(ledger),
        options["window"],
        options["minimum"],
        base["information_lag_months"],
    )
    scale = scale.reindex(returns.index).fillna(1.0)
    return replace(parts, risk_model=ScaledRiskModel(parts.risk_model, scale))


def build_forecasts(returns, meta, base, settings, model="correlated", daily=None):
    """Return (targets by strategy, covariance by month, diagnostics), without the rescale."""
    parts = configured_components(base, settings, meta, model, daily)
    return forecasts_from(parts, returns, meta, base, model)


def forecasts_from(parts: QpsComponents, returns, meta, base, model="correlated"):
    """Targets for already composed components: the step shared by every qps variant."""
    return construct_targets(
        MarketData(returns, meta),
        parts.signals,
        parts.risk_model,
        parts.sizer,
        parts.limits,
        lag=base["information_lag_months"],
        start=base["start"],
        end=base["end"],
        class_balanced=model == "class_balanced",
        adjustment=parts.adjustment,
    )


def eligibility(returns, meta, base, settings, daily=None) -> pd.DataFrame:
    """Markets with a known trend signal and positive volatility each month, minus exclusions."""
    return eligibility_from(
        configured_components(base, settings, meta, daily=daily), returns, meta, base
    )


def eligibility_from(parts: QpsComponents, returns, meta, base) -> pd.DataFrame:
    """Eligibility for already composed components: the step shared by every qps variant."""
    signal = lagged(parts.signals["trend"].forecast(returns), base["information_lag_months"])
    vol = parts.risk_model.volatility(MarketData(returns, meta))
    return parts.sizer.eligibility(signal, vol)
