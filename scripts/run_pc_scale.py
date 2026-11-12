"""Scale-stage tests S1 to S4: limit against vol target, gross cap sweep, configured model, tails.

The raw (unlimited) TREND book is scaled each month by min(g / gross, c / risk), clipped at 1 for
a limit and left free for a target. The same band, costs and executed limits then apply. Paired
Sharpe differences use the shared resampled months; deflation counts every arm and ceiling tried.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from risk_model_study import Study, load_study, paired_sharpe_difference, rolling_model, summarize
from scipy.stats import kurtosis, norm

from src.backtest.engine import simulate
from src.backtest.performance import deflated_sharpe
from src.backtest.qps_baseline import (
    configured_components,
    forecasts_from,
    qps_components,
    rescaled_components,
)
from src.config import CONFIG_DIR
from src.portfolio_construction import BandPolicy, PortfolioLimits
from src.risk_model import portfolio_risk, standardized_returns
from src.transaction_cost_model import LinearBpsCost


def model_parts(study: Study, name: str):
    """Components for a named risk model: the rolling baseline or the configured DCC-GARCH."""
    settings, base, _, source, known, meta = study.inputs
    if name == "rolling":
        return qps_components(base, settings, meta, rolling_model(study))
    parts = configured_components(base, settings, meta, daily=study.daily)
    returns = study.inputs[2]
    return rescaled_components(parts, returns, meta, base, settings, source, known)


def raw_book(study: Study, parts):
    """Unlimited TREND targets, covariance, and each month's gross and forecast risk."""
    _, base, returns, _, _, meta = study.inputs
    unlimited = replace(parts, limits=PortfolioLimits(np.inf, np.inf))
    targets, covariance, _ = forecasts_from(unlimited, returns, meta, base)
    raw = targets["trend"]
    months = [m for m in raw.index if (raw.loc[m] != 0).sum() >= base["minimum_instruments"]]
    book = pd.DataFrame(
        {
            "gross": [np.abs(raw.loc[m]).sum() for m in months],
            "risk": [portfolio_risk(raw.loc[m].to_numpy(), covariance[m]) for m in months],
        },
        index=months,
    )
    return raw, covariance, book


def run_arm(study: Study, raw, covariance, book, ceiling, arm):
    """Ledger of one arm at one ceiling."""
    settings, base, returns, source, known, _ = study.inputs
    scale = (arm["gross_cap"] / book.gross).combine(ceiling / book.risk, min)
    if not arm["lever_up"]:
        scale = scale.clip(upper=1.0)
    targets = raw.mul(scale.reindex(raw.index).fillna(0.0), axis=0)
    sample = returns.loc[base["start"] : base["end"]]
    policy = BandPolicy(
        covariance, PortfolioLimits(arm["gross_cap"], ceiling), settings["primary_band"]
    )
    ledger, _ = simulate(
        sample,
        targets,
        LinearBpsCost(settings["primary_cost_bps"]),
        source.loc[sample.index],
        position_policy=policy,
        source_known_at=known.loc[sample.index],
    )
    return ledger, scale


def run_grid(study: Study, model: str, config):
    """Ledgers by (arm, ceiling) and the summary rows for one risk model."""
    raw, covariance, book = raw_book(study, model_parts(study, model))
    ledgers, rows = {}, []
    for arm in config["arms"]:
        for ceiling in config["ceilings"]:
            ledger, scale = run_arm(study, raw, covariance, book, ceiling, arm)
            ledgers[arm["name"], ceiling] = ledger
            row = summarize(ledger)
            row["share_levered_up"] = (scale > 1 + 1e-12).mean()
            row["share_gross_binds"] = (book.gross > arm["gross_cap"]).mean()
            row["mean_gross"] = ledger.gross_exposure.mean()
            rows.append({"model": model, "policy": arm["name"], "ceiling": ceiling, **row})
    return ledgers, pd.DataFrame(rows)


def paired_rows(ledgers, grid, config):
    """S1: each target arm minus the reference limit, at the same ceiling and at matched vol."""
    ref = config["reference"]
    reference = ledgers[ref["policy"], ref["ceiling"]].net_return
    ref_vol = grid[(grid.policy == ref["policy"]) & (grid.ceiling == ref["ceiling"])].vol_ann.iloc[
        0
    ]
    rows = []
    for arm in config["arms"][1:]:
        sub = grid[grid.policy == arm["name"]]
        matched = (sub.vol_ann - ref_vol).abs().idxmin()
        picks = {"same_ceiling": [ref["ceiling"]], "matched_vol": [sub.loc[matched, "ceiling"]]}
        for kind, ceilings in picks.items():
            ceiling = ceilings[0]
            net = ledgers[arm["name"], ceiling].net_return
            stats = paired_sharpe_difference(net, reference, **config["bootstrap_args"])
            vol = sub[sub.ceiling == ceiling].vol_ann.iloc[0]
            rows.append(
                {
                    "policy": arm["name"],
                    "comparison": kind,
                    "ceiling": ceiling,
                    "vol_ann": vol,
                    **stats,
                }
            )
    return pd.DataFrame(rows)


def deflate(ledgers, config):
    """Deflated Sharpe of each target-minus-reference difference, for the trials actually run."""
    ref = config["reference"]
    reference = ledgers[ref["policy"], ref["ceiling"]].net_return
    diffs = {
        k: v.net_return - reference
        for k, v in ledgers.items()
        if k != (ref["policy"], ref["ceiling"])
    }
    trial_sharpes = np.array([d.mean() / d.std(ddof=1) for d in diffs.values()])
    counts = [len(diffs), *config["deflation_trial_counts"]]
    rows = {
        f"{arm}_{ceiling:.0%}": {
            f"trials_{n}": deflated_sharpe(d, trial_sharpes, n) for n in counts
        }
        for (arm, ceiling), d in diffs.items()
    }
    return pd.DataFrame(rows).T.rename_axis("arm_ceiling")


def tail_rows(ledgers, model, config):
    """S4: share of standardised returns below -k sigma against the Gaussian share."""
    rows = []
    for arm in config["tail_arms"]:
        z = standardized_returns(ledgers[arm, config["reference"]["ceiling"]])
        row = {
            "model": model,
            "policy": arm,
            "months": len(z),
            "std": z.std(ddof=1),
            "excess_kurtosis": kurtosis(z),
        }
        for k in config["tail_thresholds"]:
            row[f"below_-{k:g}"] = (z < -k).mean()
            row[f"below_-{k:g}_after_rescale"] = (z / z.std(ddof=1) < -k).mean()
            row[f"gaussian_-{k:g}"] = norm.cdf(-k)
        rows.append(row)
    return pd.DataFrame(rows)


def main(out):
    if out.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    config = json.loads((CONFIG_DIR / "pc_scale.json").read_text())
    config["bootstrap_args"] = {
        "block": config["bootstrap"]["block_months"],
        "draws": config["bootstrap"]["draws"],
        "seed": config["bootstrap"]["seed"],
    }
    study = load_study()
    out.mkdir(parents=True)
    (out / "trial_specification.json").write_text(json.dumps(config, indent=2) + "\n")
    grids, paired, deflated, tails = [], [], [], []
    for model in config["models"]:
        ledgers, grid = run_grid(study, model, config)
        grids.append(grid)
        paired.append(paired_rows(ledgers, grid, config).assign(model=model))
        deflated.append(deflate(ledgers, config).assign(model=model))
        tails.append(tail_rows(ledgers, model, config))
    pd.concat(grids).to_csv(out / "grid.csv", index=False)
    pd.concat(paired).to_csv(out / "paired.csv", index=False)
    pd.concat(deflated).to_csv(out / "deflated_sharpe.csv")
    pd.concat(tails).to_csv(out / "tails.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
