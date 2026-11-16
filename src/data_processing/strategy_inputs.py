"""Past-only source selection, separate from the exact supplied-data reproduction."""

import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, QPS_OUTPUT_DIR
from src.data_loader import load_daily_prices
from src.data_processing.endpoints import close_frames, endpoints
from src.risk_model import daily_returns

ROOT = PROJECT_ROOT


def select_source(own_returns, fallback_returns, months, minimum_history=36, decision_lag=2):
    """Commit to ER only after a complete past window, then never backfill from RL.

    Rule is fixed before evaluating performance. It does not inspect RL's future
    end date or this month's realized return to decide which source to hold.
    """
    if minimum_history < 1 or decision_lag < 1:
        raise ValueError("Source selection requires positive history and lag")
    selected = pd.Series(index=months, dtype=float)
    source = pd.Series("RL", index=months, dtype=object)
    records = []
    adopted = False
    for month in months:
        cutoff = month - decision_lag
        window = pd.period_range(cutoff - minimum_history + 1, cutoff, freq="M")
        available = fallback_returns.reindex(window).notna().all()
        if available:
            adopted = True
        chosen = "ER" if adopted else "RL"
        source.loc[month] = chosen
        selected.loc[month] = (fallback_returns if adopted else own_returns).get(month, np.nan)
        records.append(
            {
                "month": month,
                "source": chosen,
                "information_through": cutoff,
                "source_known_at": cutoff.end_time,
                "complete_fallback_window": bool(available),
            }
        )
    return selected, source, pd.DataFrame(records)


def _price_source(prices, months, settings):
    """Apply the same prior-only source rule to independently constructed returns."""
    frames = close_frames(prices[["RL", "ER"]])
    monthly = pd.DataFrame({
        name: endpoints(frame, months).endpoint_close for name, frame in frames.items()
    }).pct_change(fill_method=None)
    rule = settings.get("source_selection", {})
    return select_source(
        monthly.RL, monthly.ER, months,
        rule.get("minimum_history", 36), rule.get("decision_lag_months", 2),
    )


def _risk_prices(prices, markets, excluded):
    """Form the observation grid from declared estimation sources before taking ratios."""
    retained = [market for market in markets if market not in excluded]
    required = retained + (["ER"] if "RL" in retained and "ER" not in retained else [])
    missing = set(required) - set(prices.columns)
    if missing:
        raise ValueError(f"Missing daily estimation prices: {sorted(missing)}")
    if not retained:
        raise ValueError("Daily risk returns require at least one estimation market")
    panel = prices[required].dropna(how="all")
    if panel.empty:
        raise ValueError("Daily estimation markets have no observed prices")
    return panel, retained


def source_consistent_daily_returns(prices, source, markets=None, excluded=()):
    """Use each selected contract's own daily return, without a cross-price ratio.

    A missing RL observation must not remove ER from the risk universe once ER
    has been selected for that month. Source decisions are supplied separately
    and must cover every requested daily observation. Excluded and unused files
    cannot insert observation dates into the retained markets' return grid.
    """
    prices, retained = _risk_prices(prices, source.columns if markets is None else markets, excluded)
    result = daily_returns(prices)
    if "RL" not in retained:
        return result
    if "RL" not in source:
        raise ValueError("Daily risk returns require a complete RL/ER source schedule")
    chosen = source.RL.reindex(result.index.to_period("M"))
    if chosen.isna().any() or not chosen.isin(["RL", "ER"]).all():
        raise ValueError("Daily risk returns require a complete RL/ER source schedule")
    if "ER" not in result or "RL" not in result:
        raise ValueError("Daily risk returns require both RL and ER prices")
    result["RL"] = np.where(chosen.eq("ER").to_numpy(), result.ER, result.RL)
    return result[retained]


def load_strategy_inputs(settings, write=False):
    # The input file's RL fallback is retrospective; replace it and its source
    # schedule below before constructing strategy signals or positions.
    returns = pd.read_csv(QPS_OUTPUT_DIR / "construction/monthly_returns_research.csv", index_col=0)
    returns.index = pd.PeriodIndex(returns.index, freq="M")
    selected, chosen, schedule = _price_source(load_daily_prices(), returns.index, settings)
    returns["RL"] = selected
    # A predeclared source label remains defined even if a realized return is missing.
    source = pd.DataFrame({a: a for a in returns.columns}, index=returns.index)
    source["RL"] = chosen
    known_at = pd.Series(
        pd.to_datetime(schedule.source_known_at).to_numpy(),
        index=returns.index,
        name="source_known_at",
    )
    if write:
        out = QPS_OUTPUT_DIR / "construction"
        returns.to_csv(out / "monthly_returns_strategy.csv", float_format="%.17g")
        source.to_csv(out / "strategy_source.csv")
        known_at.to_csv(out / "strategy_source_known_at.csv")
        schedule.to_csv(out / "strategy_source_schedule.csv", index=False)
    return returns, source, known_at, schedule


def load_daily_returns(markets, settings=None, excluded=()) -> pd.DataFrame:
    """Daily risk returns using the monthly strategy's prior-only source rule."""
    prices, retained = _risk_prices(load_daily_prices(), markets, excluded)
    months = pd.period_range(prices.index.min().to_period("M"), prices.index.max(), freq="M")
    source = pd.DataFrame(index=months)
    if "RL" in retained:
        _, source["RL"], _ = _price_source(prices, months, settings or {})
    return source_consistent_daily_returns(prices, source, retained)
