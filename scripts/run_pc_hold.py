"""Hold-stage tests P0, P1, P2, P3 and P5: class budgets, class caps and HRP against inverse-vol.

Every variant reshapes the sized TREND book (`construct_targets(adjustment=...)`) and then runs
through the same limits, 10% band and 2 bps cost as the baseline. Variants are compared at
matched realised volatility: Sharpe is scale-free, and mean return and drawdown are rescaled
by baseline volatility over variant volatility.
"""

import argparse
import json
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
from risk_model_study import Study, load_study
from run_pc_scale import model_parts

from src.alpha_model import lagged
from src.backtest.cross_validation import cpcv_paths, cpcv_splits
from src.backtest.engine import simulate
from src.backtest.performance import deflated_sharpe, performance, sharpe_ratio
from src.backtest.sample_diagnostics import risk_diagnostics
from src.config import CONFIG_DIR
from src.models import MarketData
from src.portfolio_construction import BandPolicy, construct_targets
from src.portfolio_construction.hold import HrpSizing, cap_class_risk
from src.portfolio_construction.hold.class_balance import balance_classes, balance_factors
from src.transaction_cost_model import LinearBpsCost

MONTHS = 12


def adjustment_for(spec, limits):
    """The hold-stage reshaping a variant specification names."""
    kind = spec["kind"]
    if kind == "inverse_vol":
        return None
    if kind == "class_balanced":
        return partial(balance_classes, risk_ceiling=limits.risk_ceiling, scale_up=spec["scale_up"])
    if kind == "class_cap":
        return partial(cap_class_risk, cap=spec["cap"])
    if kind == "hrp":
        return HrpSizing(spec["within_class"], spec["signed"])
    raise ValueError(f"Unknown variant kind {kind!r}")


def run_variant(study: Study, parts, spec):
    """Targets, covariance and ledger of one variant (trend only)."""
    settings, base, returns, source, known, meta = study.inputs
    targets, covariance, _ = construct_targets(
        MarketData(returns, meta),
        {"trend": parts.signals["trend"]},
        parts.risk_model,
        parts.sizer,
        parts.limits,
        lag=base["information_lag_months"],
        start=base["start"],
        end=base["end"],
        adjustment=adjustment_for(spec, parts.limits),
    )
    sample = returns.loc[base["start"] : base["end"]]
    ledger, _ = simulate(
        sample,
        targets["trend"],
        LinearBpsCost(settings["primary_cost_bps"]),
        source.loc[sample.index],
        position_policy=BandPolicy(covariance, parts.limits, settings["primary_band"]),
        source_known_at=known.loc[sample.index],
    )
    return targets["trend"], covariance, ledger


def construction_diagnostics(target, covariance, labels, minimum):
    """P0: effective bets (1 / sum of squared risk contributions) and class risk shares by month."""
    rows = []
    for month in target.index:
        w = target.loc[month].to_numpy()
        active = w != 0
        if active.sum() < minimum:
            continue
        contribution = w * (covariance[month] @ w) / (w @ covariance[month] @ w)
        shares = pd.Series(contribution, index=target.columns).groupby(labels).sum()
        rows.append(
            {
                "month": month,
                "markets": int(active.sum()),
                "effective_bets": 1 / np.sum(contribution[active] ** 2),
                "max_class_share": shares.max(),
                **shares.add_prefix("share_").to_dict(),
            }
        )
    return pd.DataFrame(rows).set_index("month")


def max_drawdown(net):
    wealth = (1 + net).cumprod()
    return (wealth / wealth.cummax().clip(lower=1) - 1).min()


def summary_row(name, ledger, diagnostics, baseline, config):
    performed = performance(ledger)
    scale = baseline.net_return.std() / ledger.net_return.std()
    matched = ledger.net_return * scale
    return {
        "variant": name,
        "sharpe": performed["sharpe"],
        "vol_ann": performed["vol_ann"],
        "matched_mean_ann": matched.mean() * MONTHS,
        "matched_max_drawdown": max_drawdown(matched),
        "turnover_ann": performed["turnover_ann"],
        "matched_cost_ann": ledger.cost.mean() * MONTHS * scale,
        "calibration": risk_diagnostics(ledger)[1]["realized_predicted_ratio"],
        "effective_bets": diagnostics.effective_bets.mean(),
        "effective_bets_min": diagnostics.effective_bets.min(),
        "max_class_share": diagnostics.max_class_share.mean(),
        "months_class_over_cap": (
            diagnostics.max_class_share > config["concentration_share"]
        ).mean(),
    }


def balance_check(study: Study, parts, covariance, labels):
    """P1: how often does the equal-budget model raise a class above its raw size?"""
    _, base, returns, _, _, meta = study.inputs
    data = MarketData(returns, meta)
    forecast = lagged(parts.signals["trend"].forecast(returns), base["information_lag_months"])
    weights, eligible = parts.sizer.weights(forecast, parts.risk_model.volatility(data))
    rows = []
    for month in covariance:
        active = eligible.loc[month].to_numpy()
        if active.sum() < base["minimum_instruments"]:
            continue
        raw = weights.loc[month].to_numpy()
        factors = balance_factors(raw, covariance[month], labels, active, parts.limits.risk_ceiling)
        rows.append({"month": month, **{f"factor_{k}": v for k, v in factors.items()}})
    factor = (
        pd.DataFrame(rows).set_index("month").rename(columns=lambda c: c.replace("factor_", ""))
    )
    return pd.DataFrame(
        {"mean_factor": factor.mean(), "share_months_enlarged": factor.gt(1).mean()}
    )


def block_indices(n, block, draws, seed):
    """Circular moving-block resamples of the calendar, shared by all variants."""
    heads = np.random.default_rng(seed).integers(0, n, size=(draws, (n + block - 1) // block))
    return ((heads[:, :, None] + np.arange(block)) % n).reshape(draws, -1)[:, :n]


def bootstrap(nets, turnovers, bets, config):
    """P3: distribution across resampled calendars of out-of-sample vol, Sharpe, turnover, bets.

    Positions at month t use only data before t, so each month's return is out of sample for its
    weights. Months are resampled; weights are not re-estimated.
    """
    options = config["bootstrap"]
    index = block_indices(len(nets), options["block_months"], options["draws"], options["seed"])
    draws = {}
    for name in nets:
        net = nets[name].to_numpy()[index]
        draws[name] = {
            "vol": net.std(axis=1, ddof=1) * np.sqrt(MONTHS),
            "sharpe": net.mean(axis=1) / net.std(axis=1, ddof=1) * np.sqrt(MONTHS),
            "turnover": turnovers[name].to_numpy()[index].mean(axis=1) * MONTHS,
            "bets": np.nanmean(bets[name].to_numpy()[index], axis=1),
        }
    tail = (1 - options["confidence"]) / 2
    base = draws[config["baseline"]]
    better = {"vol": np.less, "sharpe": np.greater, "turnover": np.less, "bets": np.greater}
    rows = []
    for name, metrics in draws.items():
        row = {"variant": name}
        for metric, values in metrics.items():
            row[f"{metric}_median"] = np.median(values)
            row[f"{metric}_low"], row[f"{metric}_high"] = np.quantile(values, [tail, 1 - tail])
            row[f"{metric}_better_than_baseline"] = better[metric](values, base[metric]).mean()
        rows.append(row)
    return pd.DataFrame(rows)


def variant_cpcv(nets: pd.DataFrame, baseline: str, config):
    """P5: pick the variant with the best training Sharpe, score it on held-out months."""
    options = config["cpcv"]
    splits = cpcv_splits(
        len(nets), options["groups"], options["test_groups"], options["embargo_months"]
    )
    rows, picks = [], []
    for split in splits:
        train = nets.iloc[split.train].apply(sharpe_ratio)
        test = nets.iloc[split.test].apply(sharpe_ratio)
        chosen = train.idxmax()
        picks.append(chosen)
        rows.append(
            {
                "test_groups": split.test_groups,
                "chosen": chosen,
                "train_sharpe": train[chosen],
                "test_sharpe": test[chosen],
                "baseline_test_sharpe": test[baseline],
                "test_rank": int(test.rank(ascending=False)[chosen]),
                "candidates": len(test),
            }
        )
    groups = np.array_split(np.arange(len(nets)), options["groups"])
    paths = []
    for number, path in enumerate(cpcv_paths(splits, options["groups"]), start=1):
        chosen = [picks[path[g]] for g in range(options["groups"])]
        stitched = pd.concat(
            [nets[name].iloc[idx] for name, idx in zip(chosen, groups, strict=True)]
        )
        paths.append({"path": number, "chosen": chosen, "sharpe": sharpe_ratio(stitched)})
    return pd.DataFrame(rows), pd.DataFrame(paths)


def deflation(nets: pd.DataFrame, baseline: str, config):
    """Deflated Sharpe of each variant's returns, and of its return difference from the baseline.

    The levels are all far above any selection effect. The difference is the relevant test:
    does a variant beat the baseline by more than the best of n similar variants would by luck?
    """
    columns = {}
    for label, series in {
        "levels": nets,
        "difference": nets.drop(columns=baseline).sub(nets[baseline], axis=0),
    }.items():
        trial_sharpes = (series.mean() / series.std(ddof=1)).to_numpy()
        for n in [len(series.columns), *config["deflation_trial_counts"]]:
            columns[f"{label}_trials_{n}"] = pd.Series(
                {c: deflated_sharpe(series[c], trial_sharpes, n) for c in series}
            )
    return pd.DataFrame(columns).rename_axis("variant")


def main(out, model="rolling"):
    if out.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    config = json.loads((CONFIG_DIR / "pc_hold.json").read_text())
    study = load_study()
    _, base, returns, _, _, meta = study.inputs
    parts = model_parts(study, model)
    labels = meta.AssetClass.reindex(returns.columns).to_numpy()
    results = {spec["name"]: run_variant(study, parts, spec) for spec in config["variants"]}
    diagnostics = {
        name: construction_diagnostics(t, c, labels, base["minimum_instruments"])
        for name, (t, c, _) in results.items()
    }
    ledgers = {name: result[2] for name, result in results.items()}
    reference = ledgers[config["baseline"]]
    out.mkdir(parents=True)
    (out / "trial_specification.json").write_text(json.dumps(config, indent=2) + "\n")
    pd.DataFrame(
        [summary_row(n, ledgers[n], diagnostics[n], reference, config) for n in ledgers]
    ).to_csv(out / "variants.csv", index=False)
    pd.concat(diagnostics, names=["variant"]).to_csv(out / "diagnostics.csv")
    balance_check(study, parts, results[config["baseline"]][1], labels).to_csv(
        out / "balance_check.csv"
    )
    nets = pd.DataFrame({n: ledgers[n].net_return for n in ledgers})
    turnovers = pd.DataFrame({n: ledgers[n].turnover for n in ledgers})
    bets = pd.DataFrame({n: diagnostics[n].effective_bets for n in ledgers}).reindex(nets.index)
    bootstrap(nets, turnovers, bets, config).to_csv(out / "bootstrap.csv", index=False)
    splits, paths = variant_cpcv(nets, config["baseline"], config)
    splits.to_csv(out / "cpcv_splits.csv", index=False)
    paths.to_csv(out / "cpcv_paths.csv", index=False)
    deflation(nets, config["baseline"], config).to_csv(out / "deflated_sharpe.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=["rolling", "configured"], default="rolling")
    args = parser.parse_args()
    main(args.output.resolve(), args.model)
