"""Validate normalized daily-price inputs and construct causal strategy returns."""

import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_loader import load_asset_map, load_daily_prices
from src.data_processing.endpoints import close_frames, endpoints
from src.data_processing.strategy_inputs import select_source
from src.risk_model import daily_returns

PROVENANCE_FIELDS = {
    "vendor", "vintage", "timezone", "price_definition", "continuous_contract_adjustment",
    "availability_convention",
}
DECLARATION_FIELDS = {
    "evaluation_start", "evaluation_end", "shadow_start", "primary_information_lag_months",
    "information_lags_months", "initial_positions", "liquidate_at_end", "execution_convention",
    "cash_interest", "ordinary_cost_bps", "trading_band", "universe", "provenance",
}


def _month(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError(f"{name} must have the form YYYY-MM")
    try:
        return pd.Period(value, freq="M")
    except ValueError as error:
        raise ValueError(f"Invalid {name}: {value}") from error


def validate_declaration(declaration, base, risk):
    """Require a fixed comparison and an explicitly declared development/evaluation split."""
    if set(declaration) != DECLARATION_FIELDS:
        raise ValueError("Declaration must contain exactly the documented fields")
    start = _month(declaration["evaluation_start"], "evaluation_start")
    end = _month(declaration["evaluation_end"], "evaluation_end")
    shadow = _month(declaration["shadow_start"], "shadow_start")
    if start <= pd.Period(base["end"], freq="M") or end < start or shadow >= start:
        raise ValueError("Evaluation must follow development and have a prior shadow period")
    if (declaration["information_lags_months"] != [1, 2]
            or any(type(lag) is not int for lag in declaration["information_lags_months"])):
        raise ValueError("The declared information lags must be [1, 2]")
    if (type(declaration["primary_information_lag_months"]) is not int
            or declaration["primary_information_lag_months"] != 1):
        raise ValueError("The primary information lag must be 1 month")
    fixed = {
        "initial_positions": "flat", "liquidate_at_end": True,
        "execution_convention": "idealized_prior_endpoint", "cash_interest": "zero",
        "ordinary_cost_bps": risk["primary_cost_bps"], "trading_band": risk["primary_band"],
    }
    if any(declaration[name] != value for name, value in fixed.items()):
        raise ValueError("Declared execution, cost and starting-state settings must match the comparison")
    if type(declaration["liquidate_at_end"]) is not bool:
        raise ValueError("liquidate_at_end must be a boolean")
    if risk.get("risk_model", {}).get("type") != "dcc_garch":
        raise ValueError("This comparison requires the configured DCC-GARCH risk model")
    rescale = risk["risk_model"].get("rescale")
    if not rescale:
        raise ValueError("This comparison requires the configured baseline risk rescale")
    window, minimum = rescale.get("window"), rescale.get("minimum")
    if (type(window) is not int or type(minimum) is not int
            or minimum < 2 or window < minimum):
        raise ValueError("Risk rescale requires an integer window and at least two observations")
    if type(risk["volatility_months"]) is not int or risk["volatility_months"] < 1:
        raise ValueError("Risk volatility window must be a positive integer")
    values = (risk["gross_cap"], risk["portfolio_risk_ceiling"], base["instrument_volatility_scale"])
    if not all(np.isfinite(value) and value > 0 for value in values):
        raise ValueError("Gross cap, risk ceiling and instrument scale must be positive and finite")
    if not (np.isfinite(risk["primary_band"]) and 0 <= risk["primary_band"] < 1
            and np.isfinite(risk["primary_cost_bps"]) and risk["primary_cost_bps"] >= 0):
        raise ValueError("Trading band and cost must be finite and within their valid ranges")
    if not 0 < risk["risk_model"]["correlation_shrinkage"] <= 1:
        raise ValueError("DCC-GARCH shrinkage must be in (0, 1]")
    rule = risk.get("source_selection", {})
    if (type(rule.get("minimum_history")) is not int or rule["minimum_history"] < 1
            or type(rule.get("decision_lag_months")) is not int or rule["decision_lag_months"] < 1):
        raise ValueError("Source selection requires positive integer history and lag")
    min_shadow = max(risk["volatility_months"], minimum + 1)
    if (start - shadow).n < min_shadow:
        raise ValueError(f"Shadow period must contain at least {min_shadow} prior months")
    universe = declaration["universe"]
    if (
        not isinstance(universe, list) or not universe
        or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name) for name in universe)
        or len(set(universe)) != len(universe)
        or any(name.startswith("REPLACE") for name in universe)
    ):
        raise ValueError("Universe must be an explicit list of unique market IDs")
    if "RL" in universe and "ER" in universe:
        raise ValueError("ER is a fallback source for RL, not a separate strategy market")
    if len(set(universe) - set(base["exclude_from_strategy"])) < base["minimum_instruments"]:
        raise ValueError("Declared universe is smaller than the minimum eligible market count")
    provenance = declaration["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_FIELDS:
        raise ValueError("Provenance must contain exactly the documented fields")
    if any(not isinstance(v, str) or not v.strip() or v.startswith("REPLACE")
           for v in provenance.values()):
        raise ValueError("Complete the provenance fields; use 'unknown' where appropriate")
    return start, end, shadow


def input_paths(price_dir, asset_map_path, universe):
    """Resolve only predeclared market files and the RL fallback when needed."""
    markets = list(universe) + (["ER"] if "RL" in universe else [])
    files = {"asset_map": Path(asset_map_path).resolve()}
    files.update({f"price:{name}": (Path(price_dir) / f"{name}.csv").resolve() for name in markets})
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise ValueError(f"Missing declared input files: {missing}")
    return markets, files


def load_bundle(price_dir, asset_map_path, declaration, base, risk):
    """Load declared prices and check calendar coverage without scoring returns."""
    start, end, shadow = validate_declaration(declaration, base, risk)
    markets, files = input_paths(price_dir, asset_map_path, declaration["universe"])
    prices = load_daily_prices(Path(price_dir), markets, iso_dates=True)
    meta = load_asset_map(Path(asset_map_path))
    missing = set(declaration["universe"]) - set(meta.index)
    if missing:
        raise ValueError(f"Asset map is missing declared markets: {sorted(missing)}")
    if (not isinstance(prices.index, pd.DatetimeIndex) or prices.index.tz is not None
            or not prices.index.equals(prices.index.normalize())):
        raise ValueError("Daily prices require date-only, timezone-naive CSV indices")
    active = [name for name in declaration["universe"] if name not in base["exclude_from_strategy"]]
    strategy_prices = prices[active]
    observed = strategy_prices.dropna(how="all")
    if observed.empty:
        raise ValueError("Declared strategy markets have no price observations")
    first, last = observed.index[[0, -1]].to_period("M")
    required = shadow - risk["volatility_months"] - max(declaration["information_lags_months"])
    if first > required or last < end:
        raise ValueError(f"Price coverage must span at least {required} through {end}")
    coverage = {
        "first_price_month": str(first), "last_price_month": str(last),
        "required_first_price_month": str(required), "evaluation_start": str(start),
        "evaluation_end": str(end), "shadow_start": str(shadow),
        "strategy_markets": len(declaration["universe"]),
        "per_market": {
            name: {"first": str(prices[name].first_valid_index().date()),
                   "last": str(prices[name].last_valid_index().date())}
            for name in prices
        },
    }
    return prices, meta.reindex(declaration["universe"]), files, coverage


def strategy_inputs(prices, universe, settings, end):
    """Build point-in-time monthly sources and source-consistent daily risk returns."""
    prices = prices.loc[:end.end_time]
    months = pd.period_range(prices.index.min().to_period("M"), end, freq="M")
    frames = close_frames(prices)
    closes = pd.DataFrame({name: endpoints(frame, months).endpoint_close
                           for name, frame in frames.items()})
    monthly = closes.pct_change(fill_method=None)
    returns = monthly[universe].copy()
    source = pd.DataFrame({name: name for name in universe}, index=months)
    known = pd.Series([(month - 2).end_time for month in months], index=months, name="source_known_at")
    risk_returns = daily_returns(prices)
    if "RL" in universe:
        rule = settings["source_selection"]
        selected, chosen, schedule = select_source(
            monthly.RL, monthly.ER, months, rule["minimum_history"], rule["decision_lag_months"]
        )
        returns["RL"] = selected
        source["RL"] = chosen
        known = pd.Series(pd.to_datetime(schedule.source_known_at).to_numpy(), index=months,
                          name="source_known_at")
        use_er = chosen.reindex(risk_returns.index.to_period("M")).eq("ER").to_numpy()
        # Use each source's own daily returns; never divide across RL and ER price levels.
        risk_returns["RL"] = np.where(use_er, risk_returns.ER, risk_returns.RL)
    return returns, source, known, risk_returns[universe]
