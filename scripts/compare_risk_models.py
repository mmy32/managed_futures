"""Compare covariance estimators (equal-weight 36 months, EWMA, fast/slow) on the v2 strategy.

Uses the endpoint-sensitivity returns (the only full-period run), band and cost from risk_config.json.
Writes reports/qps_baseline/output/risk_model_comparison/comparison.csv.
"""

import json
from dataclasses import replace

import pandas as pd
from run_risk_research import load_returns

from src.backtest.engine import simulate
from src.backtest.performance import performance
from src.backtest.qps_baseline import forecasts_from, portfolio_limits
from src.backtest.qps_v2 import load_rules, qps_v2_components
from src.backtest.sample_diagnostics import risk_diagnostics
from src.config import CONFIG_DIR, PROJECT_ROOT, QPS_OUTPUT_DIR
from src.data_loader import load_asset_map
from src.portfolio_construction import BandPolicy
from src.risk_model import RollingCovarianceRiskModel
from src.transaction_cost_model import LinearBpsCost

OUT = QPS_OUTPUT_DIR / "risk_model_comparison"
SUMMARY_FIELDS = [
    "sharpe",
    "cagr",
    "vol_ann",
    "max_drawdown",
    "turnover_ann",
    "mean_cost_ann",
    "realized_predicted_ratio",
]


def risk_model(settings, base, half_lives):
    return RollingCovarianceRiskModel(
        window=settings["volatility_months"],
        lag=base["information_lag_months"],
        volatility_floor=settings["volatility_floor_annual"],
        correlation_shrinkage=settings["correlation_shrinkage"],
        half_lives=half_lives,
    )


def evaluate_strategy(sample, source, known, target, covariance, settings):
    """Summary at the primary band and cost."""
    policy = BandPolicy(covariance, portfolio_limits(settings), settings["primary_band"])
    ledger, _ = simulate(
        sample,
        target,
        LinearBpsCost(settings["primary_cost_bps"]),
        source,
        position_policy=policy,
        source_known_at=known,
    )
    summary = {**performance(ledger), **risk_diagnostics(ledger)[1]}
    return pd.Series({field: summary[field] for field in SUMMARY_FIELDS})


def load_inputs():
    """Settings, base config and the endpoint-sensitivity data every comparison shares."""
    OUT.mkdir(parents=True, exist_ok=True)
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    base = json.loads((PROJECT_ROOT / settings["base_config"]).read_text())
    returns, source, known, *_ = load_returns(True, OUT, settings)
    return settings, base, returns, source, known, load_asset_map()


def compare(inputs, variants, settings=None):
    """One row per estimator and strategy; `settings` overrides risk_config.json (e.g. shrinkage)."""
    default_settings, base, returns, source, known, meta = inputs
    settings = settings or default_settings
    rules = load_rules()
    sample = returns.loc[base["start"] : base["end"]]
    rows = []
    for name, half_lives in variants.items():
        parts = replace(
            qps_v2_components(base, settings, rules, meta),
            risk_model=risk_model(settings, base, half_lives),
        )
        targets, covariance, _ = forecasts_from(parts, returns, meta, base)
        for strategy, target in targets.items():
            summary = evaluate_strategy(
                sample,
                source.loc[sample.index],
                known.loc[sample.index],
                target,
                covariance,
                settings,
            )
            rows.append({"estimator": name, "strategy": strategy, **summary})
    return pd.DataFrame(rows)


def main():
    variants = json.loads((CONFIG_DIR / "risk_model_comparison.json").read_text())["variants"]
    table = compare(load_inputs(), variants)
    table.to_csv(OUT / "comparison.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
