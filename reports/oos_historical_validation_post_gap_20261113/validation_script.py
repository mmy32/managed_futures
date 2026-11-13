"""Validate the OOS runner on already-inspected history, never as an OOS assessment.

The production guard rejects development-period evaluation. A temporary source copy changes
only that guard's end date for this test; the strategy, costs and risk settings are unchanged.
Three runs use the same historical 2009–2014 setup, a 2012 prefix, and prices mutated after
the prefix. This restricted diagnostic period begins after a documented 2006 endpoint gap;
it was not selected as a performance sample. The original code and data are never modified.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVAL_START = "2009-04"
EVAL_END = "2014-12"
SHADOW_START = "2006-03"
CUTOFF = "2012-12"
VALIDATION_GUARD = "2009-03"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_raw_inputs():
    frozen = ROOT / "reports/pc_experiment_20261105/freeze.json"
    manifest = json.loads(frozen.read_text())["raw_inputs"]
    changed = [name for name, expected in manifest.items()
               if not (ROOT / name).is_file() or sha(ROOT / name) != expected]
    if changed:
        raise ValueError(f"Frozen historical inputs changed or missing: {changed}")
    return frozen, manifest


def make_clone(root):
    """Copy runtime code; relax only the historical date guard in the temporary copy."""
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "config", root / "config")
    (root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/run_hrp_oos.py", root / "scripts")
    shutil.copy2(ROOT / "pyproject.toml", root)
    config_path = root / "config/baseline_config.json"
    baseline = json.loads(config_path.read_text())
    original_end = baseline["end"]
    if original_end != EVAL_END:
        raise ValueError("The historical validation dates require development ending in 2014-12")
    baseline["end"] = VALIDATION_GUARD
    config_path.write_text(json.dumps(baseline, indent=2) + "\n")
    return original_end


def mutate_after_cutoff(source, dest, markets):
    """Alter only close values after 2012-12, preserving earlier rows byte for byte."""
    dest.mkdir()
    for market_number, market in enumerate(markets):
        lines = (source / f"{market}.csv").read_bytes().splitlines(keepends=True)
        header = next(csv.reader([lines[0].decode("utf-8-sig")]))
        close_col = header.index("Close")
        changed = [lines[0]]
        for row_number, line in enumerate(lines[1:]):
            date = line[:10].decode("ascii")
            if date <= "2012-12-31":
                changed.append(line)
                continue
            text = line.decode("utf-8").rstrip("\r\n")
            fields = next(csv.reader([text]))
            factor = 1 + 0.03 * math.sin(row_number / 17 + market_number)
            fields[close_col] = f"{float(fields[close_col]) * factor:.8f}"
            changed.append((",".join(fields) + "\n").encode())
        (dest / f"{market}.csv").write_bytes(b"".join(changed))


def invoke(clone, *arguments):
    env = {**os.environ, "PYTHONPATH": str(clone), "OPENBLAS_NUM_THREADS": "1",
           "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    subprocess.run([sys.executable, str(clone / "scripts/run_hrp_oos.py"), *arguments],
                   cwd=clone, env=env, check=True)


def read_frame(path):
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.PeriodIndex(frame.index, freq="M")
    return frame


def independent_accounting(results, end):
    """Rebuild P&L, positions, source-switch turnover, costs and NAV without the engine."""
    returns = read_frame(results / "strategy_returns.csv.gz").loc[EVAL_START:end]
    sources = read_frame(results / "strategy_source.csv.gz").loc[EVAL_START:end]
    calendar = pd.period_range(EVAL_START, end, freq="M")
    if not returns.index.equals(calendar) or not sources.index.equals(calendar):
        raise AssertionError("Return/source calendar differs from the declared evaluation")
    known = pd.to_datetime(read_frame(results / "source_known_at.csv").iloc[:, 0].loc[calendar])
    if (known.to_numpy() >= calendar.to_timestamp().to_numpy()).any():
        raise AssertionError("A source choice was known too late")
    metrics = pd.read_csv(results / "metrics.csv").set_index(["information_lag_months", "portfolio"])
    for lag in (1, 2):
        paired = read_frame(results / f"lag{lag}_paired_returns.csv")
        for name in ("baseline", "enhanced"):
            ledger = read_frame(results / f"lag{lag}_{name}_ledger.csv.gz")
            exposure = read_frame(results / f"lag{lag}_{name}_exposure.csv.gz")
            targets = read_frame(results / f"lag{lag}_{name}_target.csv.gz")
            if not (ledger.index.equals(calendar) and exposure.index.equals(calendar)
                    and targets.index.equals(calendar) and exposure.columns.equals(returns.columns)):
                raise AssertionError("The four cases do not use matched calendars and markets")
            previous = np.zeros(len(returns.columns))
            prior_sources = None
            nav = 1.0
            for i, month in enumerate(calendar):
                weights = exposure.loc[month].to_numpy(float)
                realized = returns.loc[month].to_numpy(float)
                if (np.isnan(realized) & (np.abs(weights) > 1e-14)).any():
                    raise AssertionError(f"A held return is missing at {month}")
                realized = np.nan_to_num(realized)
                now_sources = sources.loc[month].to_numpy()
                switched = (now_sources != prior_sources) if prior_sources is not None else np.zeros(
                    len(weights), dtype=bool
                )
                traded = np.abs(weights - previous)
                traded[switched] = np.abs(weights[switched]) + np.abs(previous[switched])
                rebalance = float(traded.sum())
                terminal = float(np.abs(weights * (1 + realized)).sum()) if i == len(calendar)-1 else 0
                gross = float(weights @ realized)
                cost = (rebalance + terminal) * 2 / 10000
                net = gross - cost
                row = ledger.loc[month]
                np.testing.assert_allclose(
                    [row.gross_return, row.rebalance_turnover, row.terminal_turnover, row.cost,
                     row.net_return, row.nav_start, row.nav_end],
                    [gross, rebalance, terminal, cost, net, nav, nav * (1 + net)],
                    atol=1e-11, rtol=1e-10,
                )
                previous = weights * (1 + realized) / (1 + net)
                prior_sources = now_sources
                nav *= 1 + net
            r = ledger.net_return.to_numpy(float)
            vol = np.std(r, ddof=1) * np.sqrt(12)
            summary = metrics.loc[lag, name]
            np.testing.assert_allclose(
                [summary["mean_ann"], summary["vol_ann"], summary["zero_rate_mean_vol_ratio"]],
                [12 * np.mean(r), vol, 12 * np.mean(r) / vol], atol=1e-11, rtol=1e-10,
            )
            np.testing.assert_allclose(paired[f"{name}_net"], ledger.net_return, atol=1e-12)
            if ledger.gross_limit_breach.any() or ledger.risk_limit_breach.any():
                raise AssertionError("Executed positions breach a configured limit")
        np.testing.assert_allclose(paired.enhanced_minus_baseline,
                                   paired.enhanced_net - paired.baseline_net, atol=1e-12)


def compare_causality(original, variant, *, prefix):
    """Decisions through the cutoff cannot change when later input is removed or mutated."""
    for name in ("strategy_returns.csv.gz", "strategy_source.csv.gz", "source_known_at.csv"):
        a, b = read_frame(original / name).loc[:CUTOFF], read_frame(variant / name).loc[:CUTOFF]
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-11)
    for lag in (1, 2):
        for name in ("baseline", "enhanced"):
            for item in ("target", "exposure", "ledger", "diagnostics"):
                suffix = "csv" if item == "diagnostics" else "csv.gz"
                path = f"lag{lag}_{name}_{item}.{suffix}"
                # The prefix liquidates at the cutoff; exclude that last ledger row only.
                last = str(pd.Period(CUTOFF, "M") - 1) if prefix and item == "ledger" else CUTOFF
                a = read_frame(original / path).loc[:last]
                b = read_frame(variant / path).loc[:last]
                pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-8, atol=1e-10)


def main(output):
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a new output directory; historical checks are never overwritten")
    frozen, manifest = verify_raw_inputs()
    output.mkdir(parents=True)
    (output / "README.md").write_text(
        "# Historical validation only — not an out-of-sample assessment\n\n"
        "These files use previously inspected 2009–2014 development data. The diagnostic "
        "period starts after a known 2006 HS endpoint gap; it is not a performance sample. "
        "A temporary clone changes only the development-end guard to 2009-03 for this "
        "validation. All strategy, cost and risk settings are unchanged. Run "
        "`scripts/validate_oos_history.py` with a new output path to reproduce; mutated "
        "prices are temporary and can be regenerated.\n"
    )
    shutil.copy2(Path(__file__), output / "validation_script.py")
    declaration = json.loads((ROOT / "config/oos_declaration.example.json").read_text())
    declaration.update(evaluation_start=EVAL_START, evaluation_end=EVAL_END,
                       shadow_start=SHADOW_START)
    declaration["provenance"] = {key: "unknown: historical development data"
                                 for key in declaration["provenance"]}
    prices = ROOT / "data/raw/futures_underlying"
    asset_map = ROOT / "data/raw/AssetMapCsv.csv"
    runs = {}
    with tempfile.TemporaryDirectory(prefix="oos-history-validation-") as temp:
        temp = Path(temp)
        clone = temp / "runtime"
        clone.mkdir()
        original_end = make_clone(clone)
        altered = temp / "mutated-prices"
        markets = declaration["universe"] + (["ER"] if "RL" in declaration["universe"] else [])
        mutate_after_cutoff(prices, altered, markets)
        for label, end, data in (("original", EVAL_END, prices), ("prefix", CUTOFF, prices),
                                 ("future_mutated", EVAL_END, altered)):
            trial = {**declaration, "evaluation_end": end}
            declaration_path = output / f"{label}_declaration.json"
            declaration_path.write_text(json.dumps(trial, indent=2) + "\n")
            prepared = output / label
            print(f"Historical validation: {label}", flush=True)
            invoke(clone, "prepare", "--declaration", str(declaration_path), "--prices-dir",
                   str(data), "--asset-map", str(asset_map), "--output", str(prepared))
            invoke(clone, "run", "--prepared", str(prepared))
            results = prepared / "assessment/results"
            independent_accounting(results, end)
            runs[label] = results
        compare_causality(runs["original"], runs["prefix"], prefix=True)
        compare_causality(runs["original"], runs["future_mutated"], prefix=False)
    verify_raw_inputs()
    record = {
        "scope": "Previously inspected historical data, not independent out-of-sample evidence",
        "historical_evaluation": [EVAL_START, EVAL_END], "shadow_start": SHADOW_START,
        "causality_cutoff": CUTOFF,
        "temporary_validation_only_change": {
            "config/baseline_config.json:end": {"production": original_end,
                                                "historical_guard": VALIDATION_GUARD},
        },
        "raw_input_manifest_sha256": sha(frozen), "raw_files_verified": len(manifest),
        "validation_script_sha256": sha(output / "validation_script.py"),
        "checks": ["matching calendars and source availability", "independent P&L, cost and NAV",
                   "independent headline metrics", "position limits", "prefix replay",
                   "future price mutation", "frozen input hashes before and after"],
    }
    (output / "checks.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Historical validation checks passed: {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
