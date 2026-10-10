"""Compose the qps baseline from its config files: the one place settings become objects."""

from dataclasses import dataclass

import pandas as pd

from src.alpha_model import AlwaysLongSignal, Signal, SumReturnSignal, lagged
from src.models import MarketData
from src.portfolio_construction import InverseVolatilitySizer, PortfolioLimits, construct_targets
from src.risk_model import RiskModel, RollingCovarianceRiskModel

RISK_MODELS = ("diagonal", "correlated", "class_balanced")


@dataclass(frozen=True)
class QpsComponents:
    signals: dict[str, Signal]
    risk_model: RiskModel
    sizer: InverseVolatilitySizer
    limits: PortfolioLimits


def portfolio_limits(settings) -> PortfolioLimits:
    return PortfolioLimits(settings["gross_cap"], settings["portfolio_risk_ceiling"])


def qps_components(base, settings, model="correlated") -> QpsComponents:
    """base: baseline_config.json; settings: risk_config.json."""
    if model not in RISK_MODELS:
        raise ValueError("Unknown risk model")
    lookback = base["signal_months"]
    floor = settings["volatility_floor_annual"]
    return QpsComponents(
        signals={"trend": SumReturnSignal(lookback), "static": AlwaysLongSignal(lookback)},
        risk_model=RollingCovarianceRiskModel(
            window=settings["volatility_months"],
            lag=base["information_lag_months"],
            volatility_floor=floor,
            correlation_shrinkage=settings["correlation_shrinkage"],
            diagonal=model == "diagonal",
        ),
        sizer=InverseVolatilitySizer(
            scale=base["instrument_volatility_scale"],
            volatility_floor=floor,
            minimum_instruments=base["minimum_instruments"],
            excluded=base["exclude_from_strategy"],
        ),
        limits=portfolio_limits(settings),
    )


def build_forecasts(returns, meta, base, settings, model="correlated"):
    """Return (targets by strategy, covariance by month, diagnostics)."""
    parts = qps_components(base, settings, model)
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
    )


def eligibility(returns, meta, base, settings) -> pd.DataFrame:
    """Markets with a known trend signal and positive volatility each month, minus exclusions."""
    parts = qps_components(base, settings)
    signal = lagged(parts.signals["trend"].forecast(returns), base["information_lag_months"])
    vol = parts.risk_model.volatility(MarketData(returns, meta))
    return parts.sizer.eligibility(signal, vol)
