"""Monthly target exposures: signals sized by volatility, then bounded by portfolio limits."""

import numpy as np
import pandas as pd

from src.alpha_model import Signal, lagged
from src.models import MarketData
from src.portfolio_construction.limits import PortfolioLimits, bounded_target
from src.portfolio_construction.sizing import InverseVolatilitySizer
from src.risk_model import RiskModel, portfolio_risk
from src.risk_model.base import check_monthly_calendar


def _class_balanced(raw, matrix, labels, active, risk_ceiling):
    """Scale each asset class to an equal share of the risk ceiling."""
    classes = sorted(set(labels[np.flatnonzero(active)]))
    budget = risk_ceiling / np.sqrt(len(classes))
    for group in classes:
        chosen = (labels == group) & active
        standalone = portfolio_risk(np.where(chosen, raw, 0.0), matrix)
        if standalone > 0:
            raw[chosen] *= budget / standalone
    return raw


def construct_targets(
    data: MarketData,
    signals: dict[str, Signal],
    risk_model: RiskModel,
    sizer: InverseVolatilitySizer,
    limits: PortfolioLimits,
    lag: int,
    start: str,
    end: str,
    class_balanced: bool = False,
):
    """Return (targets by strategy, covariance by month, per-month diagnostics).

    Every strategy shares one eligibility set and one covariance forecast per month.
    """
    returns = data.returns
    check_monthly_calendar(returns)
    vol = risk_model.volatility(data)
    index = returns.loc[start:end].index
    sized = {
        name: sizer.weights(lagged(signal.forecast(returns), lag), vol)
        for name, signal in signals.items()
    }
    raw = {name: weights for name, (weights, _) in sized.items()}
    eligible = next(iter(sized.values()))[1]
    if any(not other.equals(eligible) for _, other in sized.values()):
        raise ValueError("Strategies must share one eligibility set")
    covariance, details = risk_model.covariances(data, eligible.loc[index])
    labels = data.meta.reindex(returns.columns).AssetClass.to_numpy()
    targets = {name: pd.DataFrame(0.0, index=index, columns=returns.columns) for name in signals}
    records = []
    for month in index:
        active = eligible.loc[month].to_numpy()
        matrix = covariance[month]
        for name, target in targets.items():
            weights = raw[name].loc[month].to_numpy().copy()
            if class_balanced and active.sum() >= sizer.minimum_instruments:
                weights = _class_balanced(weights, matrix, labels, active, limits.risk_ceiling)
            desired = bounded_target(weights, matrix, limits)
            target.loc[month] = desired
            records.append(
                {
                    "month": month,
                    "strategy": name,
                    "eligible": int(active.sum()),
                    "information_through": details[month]["information_through"],
                    "estimation_start": details[month]["estimation_start"],
                    "min_eigenvalue": details[month]["min_eigenvalue"],
                    "raw_gross": np.abs(weights).sum(),
                    "raw_forecast": portfolio_risk(weights, matrix),
                    "target_gross": np.abs(desired).sum(),
                    "target_forecast": portfolio_risk(desired, matrix),
                    "target_gross_limited": np.abs(weights).sum() > limits.gross_cap + 1e-12,
                    "target_risk_limited": portfolio_risk(weights, matrix)
                    > limits.risk_ceiling + 1e-12,
                }
            )
    return targets, covariance, pd.DataFrame(records)
