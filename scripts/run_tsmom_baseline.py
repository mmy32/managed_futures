"""Baseline TSMOM (Moskowitz-Ooi-Pedersen 2012): clean → signal/risk → size → simulate → report."""

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.alpha_model import CompoundedReturnSignal
from src.backtest.engine import performance, signal_hit_rate, simulate
from src.config import CONFIG_DIR, TSMOM_REPORT_DIR
from src.data_cleaning import clean
from src.data_loader import load_asset_map, load_daily_prices, load_monthly_returns
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


def load_market_data() -> MarketData:
    cleaned = clean(load_monthly_returns(), load_daily_prices(), load_asset_map())
    returns = cleaned.returns.copy()
    returns.index = returns.index.to_period("M")
    # The monthly panel starts before the daily prices; complete calendar is required downstream.
    return MarketData(returns, cleaned.asset_map, cleaned.prices)


def run(data: MarketData, config: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    lag = config["information_lag_months"]
    sizer = InverseVolatilitySizer(
        config["instrument_volatility_scale"],
        config["volatility_floor_annual"],
        config["minimum_instruments"],
    )
    targets, _, _ = construct_targets(
        data,
        {"tsmom": CompoundedReturnSignal(config["signal_months"])},
        EwmaVolatilityRiskModel(lag=lag),
        sizer,
        NO_LIMITS,
        lag=lag,
        start=config["start"],
        end=config["end"],
    )
    sample = data.returns.loc[config["start"] : config["end"]]
    # A held market with no supplied return (e.g. March 1997) earns zero rather than aborting.
    filled = sample.isna() & targets["tsmom"].ne(0)
    ledger, attribution = simulate(
        sample.mask(filled, 0.0), targets["tsmom"], ZeroCost(), liquidate=False
    )
    stacked = filled.stack()
    return ledger, attribution, [f"{m}:{market}" for m, market in stacked[stacked].index]


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


def main() -> None:
    config = json.loads((CONFIG_DIR / "tsmom_baseline.json").read_text())
    data = load_market_data()
    ledger, attribution, filled = run(data, config)
    classes = data.meta["AssetClass"]
    table = stats_table(ledger, attribution, classes, config)
    check = paper_check(ledger, attribution, config)
    check["zero_filled_held_months"] = filled
    TSMOM_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(TSMOM_REPORT_DIR / "stats.csv")
    (TSMOM_REPORT_DIR / "paper_check.json").write_text(json.dumps(check, indent=2))
    plot_cumulative(ledger, config["subsample_start"], TSMOM_REPORT_DIR / "cumulative_return.png")
    print(table.to_string(float_format=lambda v: f"{v:.3f}"))
    print(json.dumps(check, indent=2))


if __name__ == "__main__":
    main()
