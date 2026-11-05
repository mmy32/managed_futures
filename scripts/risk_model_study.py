"""Risk model study: separate windows, shrinkage by CPCV, daily data, DCC-GARCH and rescale.

Every run uses the endpoint-sensitivity data, the v2 trend signal, the 10% band and 5 bps cost,
exactly as compare_risk_models.py does; only the risk model changes. Reports realised/forecast
calibration (std of gross return over forecast monthly volatility), Sharpe, drawdown and cost.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from compare_risk_models import SUMMARY_FIELDS, load_inputs

from src.backtest.cross_validation import cpcv_paths, cpcv_splits
from src.backtest.engine import simulate
from src.backtest.performance import performance, sharpe_ratio
from src.backtest.qps_baseline import forecasts_from, portfolio_limits, qps_components
from src.backtest.sample_diagnostics import risk_diagnostics
from src.data_loader import load_daily_prices
from src.portfolio_construction import BandPolicy
from src.risk_model import (
    DailyCovarianceRiskModel,
    DccGarchRiskModel,
    RollingCovarianceRiskModel,
    ScaledRiskModel,
    daily_returns,
    standardized_returns,
    trailing_scale,
)
from src.transaction_cost_model import LinearBpsCost

STRATEGIES = ("trend", "static")


@dataclass(frozen=True)
class Study:
    inputs: tuple
    daily: pd.DataFrame

    @property
    def settings(self):
        return self.inputs[0]

    @property
    def base(self):
        return self.inputs[1]

    @property
    def meta(self):
        return self.inputs[5]


def load_study() -> Study:
    inputs = load_inputs()
    returns = inputs[2]
    daily = daily_returns(load_daily_prices())[list(returns.columns)]
    return Study(inputs, daily)


def rolling_model(study, half_lives=(None,), correlation_half_lives=None, shrinkage=None):
    settings, base = study.settings, study.base
    return RollingCovarianceRiskModel(
        window=settings["volatility_months"],
        lag=base["information_lag_months"],
        volatility_floor=settings["volatility_floor_annual"],
        correlation_shrinkage=shrinkage or settings["correlation_shrinkage"],
        half_lives=half_lives,
        correlation_half_lives=correlation_half_lives,
    )


def daily_model(study, block_days=1, shrinkage=None):
    settings, base = study.settings, study.base
    return DailyCovarianceRiskModel(
        study.daily,
        window=settings["volatility_months"],
        lag=base["information_lag_months"],
        volatility_floor=settings["volatility_floor_annual"],
        correlation_shrinkage=shrinkage or settings["correlation_shrinkage"],
        block_days=block_days,
    )


def garch_model(study, shrinkage=None):
    settings, base = study.settings, study.base
    return DccGarchRiskModel(
        study.daily,
        study.meta.AssetClass,
        window=settings["volatility_months"],
        lag=base["information_lag_months"],
        volatility_floor=settings["volatility_floor_annual"],
        correlation_shrinkage=shrinkage or settings["correlation_shrinkage"],
    )


def run(study: Study, model, settings=None, strategies=STRATEGIES) -> dict[str, pd.DataFrame]:
    """Ledger per strategy for one risk model through the full pipeline."""
    default_settings, base, returns, source, known, meta = study.inputs
    settings = settings or default_settings
    parts = qps_components(base, settings, meta, model)
    targets, covariance, _ = forecasts_from(parts, returns, meta, base)
    sample = returns.loc[base["start"] : base["end"]]
    ledgers = {}
    for name in strategies:
        policy = BandPolicy(covariance, portfolio_limits(settings), settings["primary_band"])
        ledgers[name], _ = simulate(
            sample,
            targets[name],
            LinearBpsCost(settings["primary_cost_bps"]),
            source.loc[sample.index],
            position_policy=policy,
            source_known_at=known.loc[sample.index],
        )
    return ledgers


def summarize(ledger: pd.DataFrame) -> pd.Series:
    summary = {**performance(ledger), **risk_diagnostics(ledger)[1]}
    row = {field: summary[field] for field in SUMMARY_FIELDS}
    row["gross_vol_ann"] = ledger.gross_return.std(ddof=1) * np.sqrt(12)
    row["mean_forecast_vol"] = ledger.forecast_vol_annual.mean()
    return pd.Series(row).rename({"realized_predicted_ratio": "calibration"})


def compare_models(study: Study, models: dict) -> tuple[pd.DataFrame, dict]:
    """Summary rows (one per model and strategy) and the ledgers behind them."""
    rows, all_ledgers = [], {}
    for name, model in models.items():
        all_ledgers[name] = run(study, model)
        for strategy, ledger in all_ledgers[name].items():
            rows.append({"model": name, "strategy": strategy, **summarize(ledger)})
    return pd.DataFrame(rows), all_ledgers


def separate_window_models(study: Study) -> dict:
    """B3: decay weights for volatility and for correlation, within the same 36 months."""
    models = {"equal / equal (baseline)": rolling_model(study)}
    for vol in (None, 12, 6):
        for corr in (None, 24, 12, 6):
            if vol is None and corr is None:
                continue
            name = f"vol {'equal' if vol is None else f'hl{vol}'} / corr {'equal' if corr is None else f'hl{corr}'}"
            models[name] = rolling_model(study, (vol,), (corr,))
    return models


def _stitch(series: dict[str, pd.Series], chosen: list[str], groups: list[np.ndarray]) -> pd.Series:
    return pd.concat([series[name].iloc[idx] for name, idx in zip(chosen, groups, strict=True)])


def shrinkage_cpcv(
    ledgers: dict[float, pd.DataFrame],
    baseline: float,
    n_groups: int = 8,
    n_test: int = 2,
    embargo: int = 36,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """B2: choose the shrinkage on training months, score it on held-out months (CPCV).

    `ledgers` maps each candidate shrinkage to the ledger of one strategy over the same months.
    A split picks the candidate whose training calibration is closest to 1. Returns one row per
    split (chosen shrinkage, test calibration, test Sharpe, and the baseline's on the same
    months) and one row per backtest path (all groups stitched, each tested by its own split).
    """
    names = list(ledgers)
    index = ledgers[baseline].index
    z = {k: standardized_returns(ledgers[k]).reindex(index) for k in names}
    net = {k: ledgers[k].net_return for k in names}
    splits = cpcv_splits(len(index), n_groups, n_test, embargo)
    chosen_by_split = []
    rows = []
    for split in splits:
        train_error = {k: abs(z[k].iloc[split.train].std(ddof=1) - 1) for k in names}
        best = min(train_error, key=train_error.get)
        chosen_by_split.append(best)
        rows.append(
            {
                "test_groups": split.test_groups,
                "chosen": best,
                "calibration": z[best].iloc[split.test].std(ddof=1),
                "baseline_calibration": z[baseline].iloc[split.test].std(ddof=1),
                "sharpe": sharpe_ratio(net[best].iloc[split.test]),
                "baseline_sharpe": sharpe_ratio(net[baseline].iloc[split.test]),
            }
        )
    groups = np.array_split(np.arange(len(index)), n_groups)
    paths = []
    for number, path in enumerate(cpcv_paths(splits, n_groups), start=1):
        picks = [chosen_by_split[path[g]] for g in range(n_groups)]
        stitched_z = _stitch(z, picks, groups)
        stitched_net = _stitch(net, picks, groups)
        paths.append(
            {
                "path": number,
                "chosen": picks,
                "calibration": stitched_z.std(ddof=1),
                "sharpe": sharpe_ratio(stitched_net),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(paths)


def rescaled_run(study: Study, base_model, base_ledgers: dict, window=60, minimum=24):
    """C1: scale the covariance by the trailing realised/forecast ratio of each strategy.

    The ratio at month t uses the baseline's standardized returns through t-1 (past only). The
    baseline ledger stands in for the rescaled strategy's own past, so this is an approximation:
    a rescaled strategy would have slightly different past ratios.
    """
    lag = study.base["information_lag_months"]
    out = {}
    for strategy, ledger in base_ledgers.items():
        scale = trailing_scale(standardized_returns(ledger), window, minimum, lag)
        scale = scale.reindex(study.inputs[2].index).fillna(1.0)
        out[strategy] = run(study, ScaledRiskModel(base_model, scale), strategies=(strategy,))[
            strategy
        ]
    return out


def paired_sharpe_difference(
    first: pd.Series, second: pd.Series, block: int = 12, draws: int = 2000, seed: int = 0
) -> dict[str, float]:
    """Sharpe(first) - Sharpe(second) with a paired moving-block bootstrap 90% interval.

    Both series share the resampled months, so a difference that comes from the same markets and
    months is judged against the noise in the difference itself, not in each Sharpe ratio.
    """
    both = pd.concat([first, second], axis=1).dropna().to_numpy()
    n = len(both)
    rng = np.random.default_rng(seed)
    starts = np.arange(n - block + 1)
    per_draw = -(-n // block)
    differences = np.empty(draws)
    for d in range(draws):
        pick = rng.choice(starts, per_draw)
        sample = np.concatenate([both[s : s + block] for s in pick])[:n]
        sharpe = sample.mean(axis=0) / sample.std(axis=0, ddof=1) * np.sqrt(12)
        differences[d] = sharpe[0] - sharpe[1]
    point = sharpe_ratio(pd.Series(both[:, 0])) - sharpe_ratio(pd.Series(both[:, 1]))
    low, high = np.percentile(differences, [5, 95])
    return {"difference": point, "low_5pct": low, "high_95pct": high}


def wide(table: pd.DataFrame) -> pd.DataFrame:
    """One row per model; trend and STATIC columns side by side."""
    columns = ["sharpe", "calibration", "gross_vol_ann", "max_drawdown", "turnover_ann"]
    order = list(dict.fromkeys(table.model))
    out = table.pivot(index="model", columns="strategy", values=columns).loc[order]
    return out.swaplevel(axis=1).sort_index(axis=1, level=0, sort_remaining=False)[
        [(s, c) for s in STRATEGIES for c in columns]
    ]


def variance_ratio(study: Study) -> pd.Series:
    """Variance of monthly returns over the mean within-month sum of squared daily returns.

    A ratio above 1 means daily returns are positively autocorrelated or the markets trend at
    the monthly horizon, so volatility scaled up from daily data understates monthly volatility.
    """
    returns = study.inputs[2].loc[study.base["start"] : study.base["end"]]
    squares = (study.daily**2).groupby(study.daily.index.to_period("M")).sum(min_count=15)
    both = returns.columns.intersection(squares.columns)
    ratio = returns[both].var(ddof=1) / squares.reindex(returns.index)[both].mean()
    return ratio.dropna()


def mean_correlation(study: Study, step: int = 12) -> pd.DataFrame:
    """Average pairwise correlation over each 36-month window, by return frequency.

    Uses the markets with a complete monthly and daily window, every `step` months.
    """
    returns = study.inputs[2]
    months = returns.loc[study.base["start"] : study.base["end"]].index[::step]
    window = study.settings["volatility_months"]
    rows = []
    for month in months:
        start, end = (month - window).start_time, (month - 1).end_time.normalize()
        monthly = returns.loc[month - window : month - 1]
        daily = study.daily.loc[start:end]
        markets = monthly.columns[monthly.notna().all()].intersection(
            daily.columns[daily.notna().all()]
        )
        if len(markets) < 5:
            continue
        weekly = np.log1p(daily[markets].iloc[len(daily) % 5 :]).to_numpy()
        weekly = weekly.reshape(-1, 5, len(markets)).sum(axis=1)
        mats = {
            "monthly": np.corrcoef(monthly[markets].to_numpy(), rowvar=False),
            "daily": np.corrcoef(daily[markets].to_numpy(), rowvar=False),
            "weekly": np.corrcoef(weekly, rowvar=False),
        }
        upper = np.triu_indices(len(markets), 1)
        rows.append(
            {"month": month, "markets": len(markets)}
            | {k: m[upper].mean() for k, m in mats.items()}
        )
    return pd.DataFrame(rows).set_index("month")
