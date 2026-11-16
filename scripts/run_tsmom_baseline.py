"""Causal TSMOM development baseline with declared identities and no missing-held-return fill.

Archived results used full-panel cleaning and zero-filled held returns. This paper-style baseline
keeps raw RL for both returns and volatility; it is distinct from the final matched comparison's
shared causal RL/ER policy. Use the matched OOS runner for that comparison. New baseline results
require a new output directory and remain development evidence on the previously inspected history.
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.alpha_model import CompoundedReturnSignal
from src.backtest.engine import simulate
from src.backtest.performance import performance, signal_hit_rate
from src.config import CONFIG_DIR
from src.data_loader import load_asset_map, load_daily_prices
from src.data_processing.endpoints import close_frames, endpoints
from src.models import MarketData
from src.portfolio_construction import (
    InverseVolatilitySizer,
    PortfolioLimits,
    construct_targets,
)
from src.risk_model import EwmaVolatilityRiskModel
from src.transaction_cost_model import ZeroCost

NO_LIMITS = PortfolioLimits(gross_cap=np.inf, risk_ceiling=np.inf)
STAT_COLUMNS = {
    "months": "months",
    "mean_ann": "mean_ann",
    "vol_ann": "vol_ann",
    "sharpe": "sharpe",
    "max_drawdown": "max_drawdown",
    "hit_rate_monthly": "hit_rate_monthly",
}


def market_data_from_prices(prices: pd.DataFrame, meta: pd.DataFrame, config: dict) -> MarketData:
    """Use fixed raw identities; availability affects eligibility only when it becomes known.

    No full-history quality screen, correlation grouping, price averaging or source fallback is
    used. In particular RL remains its own raw source; a missing held endpoint stops simulation.
    """
    universe = config["universe"]
    if not universe or len(set(universe)) != len(universe):
        raise ValueError("TSMOM requires a nonempty, unique predeclared universe")
    markets = [name for name in universe if name not in config["exclude_from_strategy"]]
    if not markets or set(markets) - set(prices) or set(markets) - set(meta.index):
        raise ValueError("Missing declared TSMOM prices or asset metadata")
    if not isinstance(prices.index, pd.DatetimeIndex) or not prices.index.is_unique:
        raise ValueError("Daily prices require unique dates")
    if not prices.index.is_monotonic_increasing:
        raise ValueError("Daily prices must be ordered")
    months = pd.period_range(config["history_start"], config["end"], freq="M")
    if months.empty or pd.Period(config["start"], "M") < months[0]:
        raise ValueError("TSMOM requires history_start <= start <= end")
    if pd.Period(config["start"], "M") > months[-1]:
        raise ValueError("TSMOM requires history_start <= start <= end")
    selected = prices.loc[months[0].start_time : months[-1].end_time, markets].copy()
    closes = {
        market: endpoints(frame, months, lookback=config["endpoint_lookback_calendar_days"])
        .endpoint_close
        for market, frame in close_frames(selected).items()
    }
    returns = pd.DataFrame(closes, index=months).pct_change(fill_method=None)
    return MarketData(returns, meta.loc[markets].copy(), selected)


def load_market_data(config: dict) -> MarketData:
    markets = [name for name in config["universe"] if name not in config["exclude_from_strategy"]]
    return market_data_from_prices(load_daily_prices(markets=markets), load_asset_map(), config)


def run(
    data: MarketData, config: dict, instrument_details=None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lag = config["information_lag_months"]
    sizer = InverseVolatilitySizer(
        config["instrument_volatility_scale"],
        config["volatility_floor_annual"],
        config["minimum_instruments"],
        config["exclude_from_strategy"],
    )
    targets, _, _ = construct_targets(
        data,
        {"tsmom": CompoundedReturnSignal(config["signal_months"])},
        EwmaVolatilityRiskModel(
            lag=lag,
            center_of_mass=config["ewma_center_of_mass_days"],
            trading_days=config["ewma_trading_days_per_year"],
            min_observations=config["ewma_min_observations"],
        ),
        sizer,
        NO_LIMITS,
        lag=lag,
        start=config["start"],
        end=config["end"],
    )
    sample = data.returns.loc[config["start"] : config["end"]]
    return simulate(
        sample, targets["tsmom"], ZeroCost(), liquidate=False,
        instrument_details=instrument_details,
    )


def stats_row(ledger: pd.DataFrame, attribution: pd.DataFrame) -> dict:
    stats = performance(ledger)
    row = {name: stats[key] for name, key in STAT_COLUMNS.items()}
    row["hit_rate_signal"] = signal_hit_rate(attribution)
    return row


def class_row(attribution: pd.DataFrame, classes: pd.Series, name: str) -> dict:
    """Stats of one asset class's contribution to the portfolio, in NAV return units."""
    contribution = attribution.loc[:, classes[attribution.columns] == name].sum(axis=1)
    ledger = pd.DataFrame({"net_return": contribution})
    wealth = (1 + contribution).cumprod()
    vol = contribution.std(ddof=1) * np.sqrt(12)
    held = attribution.loc[:, classes[attribution.columns] == name]
    return {
        "months": len(contribution),
        "mean_ann": contribution.mean() * 12,
        "vol_ann": vol,
        "sharpe": contribution.mean() * 12 / vol if vol else np.nan,
        "max_drawdown": (wealth / wealth.cummax().clip(lower=1) - 1).min(),
        "hit_rate_monthly": (ledger.net_return > 0).mean(),
        "hit_rate_signal": signal_hit_rate(held),
    }


def stats_table(ledger, attribution, classes, config) -> pd.DataFrame:
    rows = {}
    windows = {
        f"{config['subsample_start'][:4]}+": config["subsample_start"],
        "full": config["start"],
    }
    for label, start in windows.items():
        led, att = ledger.loc[start:], attribution.loc[start:]
        rows[f"portfolio {label}"] = stats_row(led, att)
        for name in sorted(classes.unique()):
            rows[f"{name} {label}"] = class_row(att, classes, name)
    return pd.DataFrame(rows).T


def paper_check(ledger, attribution, config) -> dict:
    """Moskowitz-Ooi-Pedersen sample: portfolio vol ~12%, Sharpe ~1.1, nearly all markets > 0."""
    window = slice(config["subsample_start"], config["paper_end"])
    led, att = ledger.loc[window], attribution.loc[window]
    stats = performance(led)
    active = att.loc[:, att.ne(0).any()]
    return {
        "window": f"{config['subsample_start']} to {config['paper_end']}",
        "vol_ann": stats["vol_ann"],
        "sharpe": stats["sharpe"],
        "markets_positive": int((active.mean() > 0).sum()),
        "markets_total": int(active.shape[1]),
    }


def plot_cumulative(ledger: pd.DataFrame, start: str, path) -> None:
    wealth = (1 + ledger.net_return.loc[start:]).cumprod()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(wealth.index.to_timestamp(), wealth.to_numpy(), color="#1f77b4", linewidth=1.5)
    ax.set_yscale("log")
    ax.set_ylabel("Growth of 1 (log scale)")
    ax.set_title(f"Baseline TSMOM, cumulative return from {start}")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(output: Path) -> None:
    if output.exists():
        raise ValueError("Use a new output directory; archived TSMOM results must be preserved")
    config = json.loads((CONFIG_DIR / "tsmom_baseline.json").read_text())
    data = load_market_data(config)
    ledger, attribution = run(data, config)
    classes = data.meta["AssetClass"]
    table = stats_table(ledger, attribution, classes, config)
    check = paper_check(ledger, attribution, config)
    check["input_policy"] = config["input_policy"]
    check["independent_validation"] = False
    output.mkdir(parents=True)
    table.to_csv(output / "stats.csv")
    (output / "paper_check.json").write_text(json.dumps(check, indent=2))
    (output / "config.json").write_text(json.dumps(config, indent=2))
    plot_cumulative(ledger, config["subsample_start"], output / "cumulative_return.png")
    print(table.to_string(float_format=lambda v: f"{v:.3f}"))
    print(json.dumps(check, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
