"""Run a historical information-lag sensitivity for the matched HRP comparison.

This uses the archived conditional 1976–2014 panel, not new evaluation data. The
second lag delays information by a month; it does not model next-session fills.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.engine import simulate
from src.backtest.hrp_comparison import comparison_components, load_comparison
from src.backtest.performance import performance
from src.backtest.qps_baseline import forecasts_from
from src.config import PROJECT_ROOT
from src.data_loader import load_asset_map
from src.data_processing.strategy_inputs import load_daily_returns
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost

REFERENCE = PROJECT_ROOT / "reports/cost_revision_20261026"
INPUTS = {
    "returns": "output/endpoint_sensitivity_v2/returns_used.csv",
    "source": "output/construction/strategy_source.csv",
    "known": "output/construction/strategy_source_known_at.csv",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_panel(path):
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.PeriodIndex(frame.index, freq="M")
    return frame


def verified_inputs():
    manifest = json.loads((REFERENCE / "ARTIFACT_SHA256.json").read_text())
    for name in INPUTS.values():
        if digest(REFERENCE / name) != manifest[name]:
            raise ValueError(f"Historical input changed: {name}")
    raw = json.loads((PROJECT_ROOT / "reports/pc_experiment_20261105/freeze.json").read_text())
    for name, expected in raw["raw_inputs"].items():
        if digest(PROJECT_ROOT / name) != expected:
            raise ValueError(f"Historical raw input changed: {name}")
    returns = read_panel(REFERENCE / INPUTS["returns"])
    source = read_panel(REFERENCE / INPUTS["source"])
    known = read_panel(REFERENCE / INPUTS["known"]).iloc[:, 0]
    return returns, source, known


def main(output):
    if output.exists():
        raise ValueError("Use a new output directory; never overwrite an earlier audit")
    spec, base, risk = load_comparison()
    if base["start"] != "1976-01" or base["end"] != "2014-12":
        raise ValueError("This audit is restricted to the declared 1976–2014 development sample")
    returns, source, known = verified_inputs()
    meta = load_asset_map()
    daily = load_daily_returns(returns.columns)
    sample = returns.loc[base["start"] : base["end"]]
    ledgers, rows = {}, []
    for lag in (1, 2):
        print(f"Historical information lag {lag}: fitting shared risk forecasts", flush=True)
        lag_base = {**base, "information_lag_months": lag}
        shared, cases = comparison_components(
            spec, lag_base, risk, returns, meta, source, known, daily
        )
        for name, parts in cases.items():
            target, covariance, _ = forecasts_from(parts, returns, meta, shared)
            ledger, _ = simulate(
                sample, target["trend"], LinearBpsCost(risk["primary_cost_bps"]),
                source.loc[sample.index], source_known_at=known.loc[sample.index],
                position_policy=BandPolicy(covariance, parts.limits, risk["primary_band"]),
            )
            np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost)
            if ledger.gross_limit_breach.any() or ledger.risk_limit_breach.any():
                raise ValueError(f"Limit breach: lag {lag}, {name}")
            ledgers[lag, name] = ledger
            rows.append({"information_lag_months": lag, "portfolio": name, **performance(ledger)})
            print(f"Completed lag {lag}: {name}", flush=True)
    output.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(output / "metrics.csv", index=False)
    for (lag, name), ledger in ledgers.items():
        ledger.to_csv(output / f"lag{lag}_{name}_ledger.csv.gz")
    files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    files += sorted((PROJECT_ROOT / "config").glob("*.json"))
    files.append(Path(__file__))
    record = {
        "sample": "1976-01 to 2014-12; inspected development data",
        "data_scenario": "conditional on the unverified March 1997 endpoint assumption",
        "execution": "idealized endpoint; lag two is not a next-session fill simulation",
        "rescale_shadow": spec["rescale_shadow"],
        "ordinary_cost_bps": risk["primary_cost_bps"],
        "band": risk["primary_band"],
        "reference_manifest_sha256": digest(REFERENCE / "ARTIFACT_SHA256.json"),
        "raw_inputs_verified": len(json.loads(
            (PROJECT_ROOT / "reports/pc_experiment_20261105/freeze.json").read_text()
        )["raw_inputs"]),
        "source_sha256": {str(p.relative_to(PROJECT_ROOT)): digest(p) for p in files},
    }
    (output / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
