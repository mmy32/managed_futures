"""Historical hold-stage comparisons with past-only walk-forward selection diagnostics.

Fixed variants use the same limits, band and costs; headline metrics are their
actual simulated returns. Previously inspected history cannot supply a fresh
holdout. Fold scores describe separate candidate ledgers, not an executable
switching portfolio, and never authorize automatic promotion. CPCV is optional
and explicitly historical because its training periods may follow test periods.
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
from src.backtest.cross_validation import cpcv_paths, cpcv_splits, walk_forward_splits
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


def summary_row(name, ledger, diagnostics, config):
    performed = performance(ledger)
    return {
        "variant": name,
        "mean_ann": performed["mean_ann"],
        "cagr": performed["cagr"],
        "sharpe": performed["sharpe"],
        "vol_ann": performed["vol_ann"],
        "max_drawdown": performed["max_drawdown"],
        "turnover_ann": performed["turnover_ann"],
        "mean_cost_ann": performed["mean_cost_ann"],
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
    """P3: sampling variation of historical vol, Sharpe, turnover and bets.

    Months and existing returns are resampled; weights are not re-estimated. These are
    development diagnostics on inspected data, not independent out-of-sample evidence.
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


def variant_walk_forward(nets: pd.DataFrame, baseline: str, config):
    """Score a past-only selection rule on separately maintained historical candidates."""
    if (nets.empty or not isinstance(nets.index, pd.PeriodIndex) or nets.index.freqstr != "M"
            or not nets.index.equals(pd.period_range(nets.index.min(), nets.index.max(), freq="M"))
            or not nets.columns.is_unique or baseline not in nets
            or not np.isfinite(nets.to_numpy()).all()):
        raise ValueError("Selection requires finite candidates on one complete monthly calendar")
    options = config["walk_forward"]
    splits = walk_forward_splits(len(nets), options["train_months"], options["test_months"],
                                options["minimum_test_months"])
    rows = []
    for fold, split in enumerate(splits, start=1):
        train, test = nets.iloc[split.train], nets.iloc[split.test]
        scores = train.apply(sharpe_ratio).replace([np.inf, -np.inf], np.nan).dropna()
        if scores.empty:
            raise ValueError(f"No varying training candidate in walk-forward fold {fold}")
        chosen = scores.idxmax()
        difference = (test[chosen] - test[baseline]).mean() * MONTHS
        rows.append({
            "fold": fold, "train_start": str(train.index[0]), "train_end": str(train.index[-1]),
            "test_start": str(test.index[0]), "test_end": str(test.index[-1]),
            "train_months": len(train), "test_months": len(test), "chosen": chosen,
            "train_sharpe": scores[chosen],
            "candidate_test_sharpe": sharpe_ratio(test[chosen]),
            "baseline_test_sharpe": sharpe_ratio(test[baseline]),
            "candidate_test_mean_ann": test[chosen].mean() * MONTHS,
            "baseline_test_mean_ann": test[baseline].mean() * MONTHS,
            "candidate_minus_baseline_mean_ann": difference,
        })
    return pd.DataFrame(rows)


def variant_cpcv(nets: pd.DataFrame, baseline: str, config):
    """P5: assess selection across historical splits, which can train on later months."""
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
        paths.append({"path": number, "chosen": chosen,
                      "stitched_candidate_sharpe_diagnostic": sharpe_ratio(stitched)})
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


def write_selection_diagnostics(out, nets, config, model):
    """Record diagnostic scores and their historical scope without a promotion decision."""
    folds = variant_walk_forward(nets, config["baseline"], config)
    folds.to_csv(out / "walk_forward_folds.csv", index=False)
    evidence = {
        "scope": "Previously inspected historical development data",
        "independent_out_of_sample": False, "automatic_promotion": False,
        "model": model, "primary_selection_diagnostic": "past_only_walk_forward",
        "walk_forward": config["walk_forward"], "folds": len(folds),
        "selection_counts": folds.chosen.value_counts().to_dict(),
        "headline_metrics": "Actual fixed-variant simulated returns in variants.csv",
        "fold_scores": "Separate candidate ledgers retain their own holdings/NAV; no switching "
                       "portfolio is simulated and no stitched portfolio performance is reported",
        "cpcv_enabled": config["cpcv"]["enabled"],
        "historical_cpcv": "Optional resampling diagnostic; training can follow testing and "
                           "finite embargo does not isolate expanding risk/calibration states",
    }
    (out / "evaluation_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if config["cpcv"]["enabled"]:
        splits, paths = variant_cpcv(nets, config["baseline"], config)
        splits.to_csv(out / "historical_cpcv_splits.csv", index=False)
        paths.to_csv(out / "historical_cpcv_paths.csv", index=False)


def main(out, model="rolling", historical_cpcv=False):
    if out.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    config = json.loads((CONFIG_DIR / "pc_hold.json").read_text())
    if historical_cpcv:
        config["cpcv"]["enabled"] = True
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
    out.mkdir(parents=True)
    (out / "trial_specification.json").write_text(json.dumps(config, indent=2) + "\n")
    pd.DataFrame(
        [summary_row(n, ledgers[n], diagnostics[n], config) for n in ledgers]
    ).to_csv(out / "variants.csv", index=False)
    pd.concat(diagnostics, names=["variant"]).to_csv(out / "diagnostics.csv")
    balance_check(study, parts, results[config["baseline"]][1], labels).to_csv(
        out / "balance_check.csv"
    )
    nets = pd.DataFrame({n: ledgers[n].net_return for n in ledgers})
    turnovers = pd.DataFrame({n: ledgers[n].turnover for n in ledgers})
    bets = pd.DataFrame({n: diagnostics[n].effective_bets for n in ledgers}).reindex(nets.index)
    bootstrap(nets, turnovers, bets, config).to_csv(out / "bootstrap.csv", index=False)
    write_selection_diagnostics(out, nets, config, model)
    deflation(nets, config["baseline"], config).to_csv(out / "deflated_sharpe.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=["rolling", "configured"], default="rolling")
    parser.add_argument("--historical-cpcv", action="store_true",
                        help="Also write the nonchronological historical CPCV diagnostic")
    args = parser.parse_args()
    main(args.output.resolve(), args.model, args.historical_cpcv)
