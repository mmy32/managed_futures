"""Audit supplied monthly inputs and publish reproducible code-verification evidence.

This command does not score a holdout or substitute monthly observations for daily GARCH data.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import json
import platform
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from markdown import markdown

from src.config import PROJECT_ROOT, RAW_DATA_DIR
from src.data_loader import (
    load_asset_map,
    load_daily_prices,
    load_full_sample_returns,
    load_monthly_returns,
)
from src.data_loader.monthly_returns import load_monthly_return_tokens
from src.data_processing.endpoints import close_frames, endpoints
from src.data_processing.input_audit import market_coverage, missing_runs, reconcile_monthly


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def source_hashes():
    files = [PROJECT_ROOT / "pyproject.toml"]
    for folder, pattern in (("src", "*.py"), ("scripts", "*.py"),
                            ("tests", "*.py"), ("config", "*.json")):
        files += sorted((PROJECT_ROOT / folder).rglob(pattern))
    return {str(p.relative_to(PROJECT_ROOT)): digest(p) for p in files}


def input_inventory(raw):
    reference = json.loads((PROJECT_ROOT / "reports/pc_experiment_20261105/freeze.json")
                           .read_text())["raw_inputs"]
    names = ["AssetMapCsv.csv", "MonthlyReturns.csv", "Lecture3_livedata.xlsx",
             "MonthlyReturns_FullSample.xlsx"]
    records = []
    for name in names:
        path = raw / name
        expected = reference.get(f"data/raw/{name}")
        actual = digest(path)
        records.append({"file": name, "path": str(path.resolve()), "bytes": path.stat().st_size,
                        "sha256": actual, "archived_sha256": expected or "",
                        "identity_status": "PASS" if actual == expected else
                        "NEW_INPUT" if expected is None else "MISMATCH"})
    daily = []
    for relative, expected in reference.items():
        if "/futures_underlying/" not in relative:
            continue
        path = raw / "futures_underlying" / Path(relative).name
        actual = digest(path) if path.is_file() else ""
        daily.append({"file": Path(relative).name, "path": str(path.resolve()),
                      "exists": path.is_file(), "sha256": actual,
                      "matches_archived_hash": actual == expected})
    return pd.DataFrame(records), pd.DataFrame(daily)


def audit_inputs(raw, output):
    output.mkdir()
    inventory, daily = input_inventory(raw)
    original = load_monthly_returns(raw / "MonthlyReturns.csv")
    original.index = original.index.to_period("M")
    tokens = load_monthly_return_tokens(raw / "MonthlyReturns.csv")
    tokens.index = tokens.index.to_period("M")
    expanded = load_full_sample_returns(raw / "MonthlyReturns_FullSample.xlsx", units="decimal")
    meta = load_asset_map(raw / "AssetMapCsv.csv")
    if set(expanded) - set(meta.index):
        raise ValueError("Full-sample markets are absent from the supplied asset map")
    overlap, changes = reconcile_monthly(original, expanded, tokens)
    base = json.loads((PROJECT_ROOT / "config/baseline_config.json").read_text())
    development_end = pd.Period(base["end"], freq="M")
    post = expanded.loc[development_end + 1:]
    coverage = market_coverage(expanded, meta, development_end)
    gaps = missing_runs(expanded, development_end + 1)
    monthly = pd.DataFrame({"observed_markets": post.notna().sum(axis=1),
                            "missing_markets": post.isna().sum(axis=1)})
    tables = {"input_inventory": inventory, "daily_file_readiness": daily,
              "overlap_changes": changes, "market_coverage": coverage,
              "post_development_missing_runs": gaps, "post_development_monthly_coverage": monthly}
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=name.endswith("monthly_coverage"))
    endpoint_table(expanded).to_csv(output / "known_endpoint_cells.csv", index=False)
    if daily.exists.all() and daily.matches_archived_hash.all():
        daily_endpoint_evidence(raw).to_csv(output / "daily_endpoint_evidence.csv", index=False)
    largest = expanded.stack().dropna().rename("return_decimal").reset_index()
    largest.columns = ["month", "market", "return_decimal"]
    largest.loc[largest.return_decimal.abs().nlargest(20).index].to_csv(
        output / "largest_monthly_moves.csv", index=False)
    summary = input_summary(expanded, post, inventory, daily, overlap, base)
    summary["known_endpoint_missing_cells"] = int(endpoint_table(expanded).status.eq("MISSING").sum())
    write_json(output / "summary.json", summary)
    coverage_chart(expanded, development_end, output / "coverage.png")
    return summary, tables


def endpoint_table(returns):
    cases = [(month, market) for month in ("1997-03", "1997-04")
             for market in ("DT", "GS", "LX", "SS")]
    cases += [(month, "HS") for month in ("2006-01", "2006-02")]
    records = []
    for month, market in cases:
        value = returns.loc[month, market]
        records.append({"month": month, "market": market,
                        "status": "MISSING" if pd.isna(value) else "OBSERVED",
                        "supplied_return": value})
    return pd.DataFrame(records)


def daily_endpoint_evidence(raw):
    """Show observed dates and freshness decisions without inventing a venue calendar."""
    prices = load_daily_prices(raw / "futures_underlying", ["DT", "GS", "LX", "SS", "HS"])
    frames = close_frames(prices)
    records = []
    for market, frame in frames.items():
        months = pd.period_range("2005-12", "2006-02", freq="M") if market == "HS" else \
            pd.period_range("1997-02", "1997-04", freq="M")
        table = endpoints(frame, months).reset_index(names="month")
        table.insert(0, "market", market)
        records.append(table)
    return pd.concat(records, ignore_index=True)


def input_summary(expanded, post, inventory, daily, overlap, base):
    passed = (not inventory.identity_status.eq("MISMATCH").any()
              and overlap["observed_changes_beyond_precision"] == 0
              and overlap["original_only_observed_cells"] == 0
              and overlap["removed_observations"] == 0
              and not (daily.exists & ~daily.matches_archived_hash).any())
    return {"input_audit_passed": bool(passed), "full_sample_months": len(expanded),
            "markets": expanded.shape[1], "start": str(expanded.index[0]),
            "end": str(expanded.index[-1]), "units": "decimal; explicitly declared, not rescaled",
            "observed_cells": int(expanded.notna().sum().sum()),
            "missing_cells": int(expanded.isna().sum().sum()),
            "development_end": base["end"], "post_development_months": len(post),
            "post_development_missing_cells": int(post.isna().sum().sum()),
            "daily_files_expected": len(daily), "daily_files_present": int(daily.exists.sum()),
            "daily_files_hash_matched": int(daily.matches_archived_hash.sum()),
            "real_data_garch_status": "NOT_RUN" if daily.exists.all() else "BLOCKED_MISSING_DAILY",
            "post_development_garch_status": "BLOCKED_NO_DAILY_EXTENSION",
            "independent_oos_assessment_performed": False, "overlap": overlap}


def coverage_chart(returns, development_end, path):
    fig, ax = plt.subplots(figsize=(13, 9))
    ax.imshow(returns.notna().T.to_numpy(), aspect="auto", interpolation="nearest",
              cmap="Blues", vmin=0, vmax=1)
    ticks = np.linspace(0, len(returns) - 1, 8, dtype=int)
    ax.set_xticks(ticks, [str(returns.index[i]) for i in ticks])
    ax.set_yticks(np.arange(len(returns.columns)), returns.columns, fontsize=7)
    boundary = int((returns.index <= development_end).sum()) - 0.5
    ax.axvline(boundary, color="darkorange", linewidth=1.5, label="End of inspected 2014 history")
    ax.set_title("Supplied monthly data coverage — blue: observed; white: missing")
    ax.set_xlabel("Data coverage only; no strategy returns or OOS scores computed")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def run_logged(command, path):
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    path.write_text("COMMAND: " + shlex.join(command) + "\n\n" + result.stdout + result.stderr)
    return {"exit_code": result.returncode, "command": command,
            "log": str(path.relative_to(path.parents[1]))}


def lint_delta(output):
    """Preserve existing findings, but fail on new findings in changed/new Python files."""
    ruff = [sys.executable, "-m", "ruff", "check", "--output-format=json"]
    current = subprocess.run([*ruff, "."], cwd=PROJECT_ROOT, capture_output=True,
                             text=True, check=False)
    (output / "ruff_findings.json").write_text(current.stdout)
    findings = json.loads(current.stdout)
    tracked = subprocess.check_output(["git", "diff", "--name-only"], cwd=PROJECT_ROOT,
                                      text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                        cwd=PROJECT_ROOT, text=True).splitlines()
    files = sorted({p for p in tracked + untracked if p.endswith(".py")})
    prior = []
    for name in files:
        old = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, check=False)
        if old.returncode == 0:
            checked = subprocess.run([*ruff, "--stdin-filename", name, "-"], input=old.stdout,
                                     cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
            prior.extend(json.loads(checked.stdout))
    paths = {str((PROJECT_ROOT / p).resolve()) for p in files}
    touched = [r for r in findings if r["filename"] in paths]
    keys = lambda rows: Counter((r["filename"], r["code"], r["message"]) for r in rows)
    introduced = keys(touched) - keys(prior)
    return {"repository_findings": len(findings), "new_findings": sum(introduced.values()),
            "passed": not introduced, "scope": "No new findings in modified/new Python files"}


def verification_checks(output, summary, raw):
    checks = output / "checks"
    checks.mkdir()
    python = sys.executable
    results = {"tests": run_logged([python, "-m", "pytest", "-q", "--junitxml",
                                    str(checks / "test_results.xml")], checks / "pytest.log"),
               "types": run_logged([python, "-m", "mypy", "src"], checks / "mypy.log"),
               "garch_numerics": run_logged([python, "scripts/verify_garch_fixes.py", "--output",
                                             str(output / "garch_checks")], checks / "garch.log")}
    results["lint"] = lint_delta(checks)
    if summary["daily_files_hash_matched"] == summary["daily_files_expected"]:
        results["original_data"] = run_logged(
            [python, "scripts/verify_original_inputs.py", "--raw-dir", str(raw),
             "--output", str(output / "historical_data_checks")], checks / "original_data.log")
        results["historical_garch"] = run_logged(
            [python, "scripts/verify_historical_garch.py", "--raw-dir", str(raw),
             "--output", str(output / "historical_garch")],
            checks / "historical_garch.log")
        summary["real_data_garch_status"] = "HISTORICAL_INTEGRATION_PASSED" if \
            results["historical_garch"]["exit_code"] == 0 else "HISTORICAL_INTEGRATION_FAILED"
    else:
        results["original_data"] = {"exit_code": None, "status": "BLOCKED_MISSING_DAILY"}
        results["historical_garch"] = {"exit_code": None, "status": "BLOCKED_MISSING_DAILY"}
    if (checks / "test_results.xml").is_file():
        suites = ET.parse(checks / "test_results.xml").getroot().iter("testsuite")
        results["tests"]["test_count"] = sum(int(s.get("tests", 0)) for s in suites)
    results["passed"] = (all(results[key]["exit_code"] == 0 for key in
                             ("tests", "types", "garch_numerics")) and results["lint"]["passed"]
                         and results["historical_garch"]["exit_code"] in (0, None))
    results["passed"] = results["passed"] and results["original_data"]["exit_code"] in (0, None)
    write_json(checks / "summary.json", results)
    return results


def md_table(frame):
    columns = list(frame.columns)
    clean = lambda value: ("—" if pd.isna(value) else str(value)).replace(
        "|", "\\|").replace("\n", " ")
    rows = ["| " + " | ".join(map(clean, columns)) + " |",
            "| " + " | ".join("---" for _ in columns) + " |"]
    rows += ["| " + " | ".join(clean(v) for v in row) + " |"
             for row in frame.itertuples(index=False, name=None)]
    return "\n".join(rows)


def input_report(summary, tables):
    inventory = tables["input_inventory"][["file", "identity_status"]].rename(
        columns={"file": "Supplied file", "identity_status": "Archived identity"})
    gaps = tables["market_coverage"].loc[lambda f: f.post_development_missing > 0,
                                        ["market", "post_development_missing", "last_observed_month"]]
    gaps = gaps.rename(columns={"market": "Market", "post_development_missing": "Missing months after development",
                                "last_observed_month": "Last observed month"})
    runs = tables["post_development_missing_runs"].copy()
    runs["resumption_return_decimal"] = runs.resumption_return_decimal.map(
        lambda value: f"{value:+.2%}" if pd.notna(value) else "Not resumed")
    runs = runs.rename(columns={"market": "Market", "gap_start": "Gap start", "gap_end": "Gap end",
                                "missing_months": "Missing months", "resumption_month": "Resumed",
                                "resumption_return_decimal": "Return when resumed"})
    return ["## Supplied inputs", md_table(inventory),
             ("PASS means byte-for-byte identity with the archived original. NEW_INPUT means the "
             "full-sample workbook has no archived original hash; its current hash is recorded."),
             (f"Full sample: **{summary['start']} through {summary['end']}**, "
             f"{summary['full_sample_months']} months and {summary['markets']} markets. "
             "Returns are decimal units: 0.01 means 1%. No scaling or filling was performed."),
             (f"The original overlap has {summary['overlap']['observed_changes_beyond_precision']} "
             "observed changes beyond the declared CSV-rounding/Excel-representation tolerance and "
             f"{summary['overlap']['added_observations']} newly supplied cells. "
             "The exact additions are shown below; they are not automatic venue-calendar repairs."),
             "Overlap tolerance: " + summary["overlap"]["tolerance_rule"], "",
             md_table(tables["overlap_changes"][["month", "market", "change", "full_sample"]]),
             "", "![Monthly data coverage](input_audit/coverage.png)", "",
             "## Data issues still requiring review", "", md_table(gaps), "",
             md_table(runs), "",
             ("Large returns after gaps require vendor/source/interval review. ZD and YM continuity "
             "also needs review before any source transition; no replacement is chosen retrospectively."),
             (f"{summary['known_endpoint_missing_cells']} of the ten flagged March/April 1997 "
             "DT/GS/LX/SS and January/February 2006 HS cells are still missing. "
             "See [exact cells](input_audit/known_endpoint_cells.csv) and "
             "[post-development gaps](input_audit/post_development_missing_runs.csv).")]


def check_report(summary, checks):
    return ["## What the code checks establish",
             (f"- Automated tests: {checks['tests'].get('test_count', 'see log')} tests, "
             f"exit {checks['tests']['exit_code']}; "
             "[test log](checks/pytest.log), [individual tests](checks/test_results.xml)."),
             f"- Type checks: exit {checks['types']['exit_code']}; [log](checks/mypy.log).",
             (f"- Ruff: {checks['lint']['new_findings']} new findings in modified/new files; "
             f"{checks['lint']['repository_findings']} existing repository findings remain."),
             ("- [Readable GARCH numerical checks](garch_checks/SUMMARY.md) use reproducible "
             "**synthetic daily observations**, not this monthly workbook or real trading performance."),
             "## What is not established",
             (f"{summary['daily_files_present']} of {summary['daily_files_expected']} original "
             f"daily price files are present; {summary['daily_files_hash_matched']} match archived hashes. "
             "Those originals end in December 2014. No daily extension through the new monthly "
             "sample was supplied, so the 2015–2025 daily-risk strategy assessment remains blocked."),
             (f"The {summary['post_development_months']} months after the inspected 2014 history "
             "are potential evaluation data. Prior access and vendor conventions are not independently "
             "certified. No strategy was scored on them, and no OOS advantage is claimed.")]


def summary_body(summary, tables, checks, output):
    status = "PASS" if checks["passed"] and summary["input_audit_passed"] else "FAILED"
    try:
        destination = str(output.relative_to(PROJECT_ROOT))
    except ValueError:
        destination = str(output)
    commands = ["## Verify this yourself", "From the repository root:",
             "```sh\n.venv/bin/python scripts/verify_research.py --verify-existing "
             + shlex.quote(destination)
             + "\n.venv/bin/python scripts/verify_research.py --output reports/my_verification\n```",
             ("The first command checks saved output, input and source hashes. "
             "The second regenerates the audits and reruns all checks in a **new** directory. "
             "A successful exit means the verification completed; the real-data GARCH status "
             "above remains separate. [Detailed guide](../../docs/VERIFYING_RESULTS.md).")]
    lead = ["# Research verification", f"**Automated verification: {status}.**",
            "**Historical real-data GARCH: " + summary["real_data_garch_status"] + ".**",
            "**2015–2025 daily-risk assessment: blocked — extended daily prices are absent.**",
            "Passing code checks does not establish profitable or independently validated performance."]
    return "\n\n".join(lead + input_report(summary, tables) + check_report(summary, checks)
                          + historical_report(output) + numerical_report(output) + commands) + "\n"


def historical_report(output):
    report = output / "historical_garch/SUMMARY.md"
    if not report.is_file():
        return ["Historical daily verification did not finish; inspect its command log if present."]
    return ["## Real historical daily-price integration",
            "[Read the original daily-to-monthly reconciliation](historical_data_checks/SUMMARY.html).",
            ("[Read the historical GARCH evidence](historical_garch/SUMMARY.html). "
            "These are fit, data and forecast diagnostics on inspected history; no portfolio "
            "performance or OOS advantage is established."),
            "[Observed dates behind the unresolved endpoints](input_audit/daily_endpoint_evidence.csv)."]


def numerical_report(output):
    folder = output / "garch_checks"
    if not (folder / "checks.csv").is_file():
        return ["Numerical checks did not finish; inspect [the command log](checks/garch.log)."]
    checks = pd.read_csv(folder / "checks.csv")
    checks["passed"] = checks.passed.map({True: "PASS", False: "FAIL"})
    state = pd.read_csv(folder / "dcc_missing_state_trace.csv")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(state.missing_steps, state.fixed_q_diagonal, label="Conditional-moment update")
    ax.plot(state.missing_steps, state.zero_shock_counterfactual_diagonal,
            label="Incorrect zero-shock counterfactual", linestyle="--")
    ax.set(xlabel="Consecutive unavailable synthetic observations", ylabel="DCC Q diagonal",
           title="Missing observations should not be recorded as zero shocks")
    ax.legend()
    fig.tight_layout()
    fig.savefig(folder / "missing_state.png", dpi=130)
    plt.close(fig)
    return ["## Numerical evidence: synthetic daily fixture",
            ("These are filter-state and code checks, not strategy profits. The expected recurrence "
            "is calculated independently; the mutation/prefix checks refit actual production models."),
            "![Missing-state numerical check](garch_checks/missing_state.png)", md_table(checks)]


def publish(output, body):
    (output / "SUMMARY.md").write_text(body)
    html = markdown(body, extensions=["tables", "fenced_code"])
    for relative in ("input_audit/coverage.png", "garch_checks/missing_state.png"):
        if (output / relative).is_file():
            png = base64.b64encode((output / relative).read_bytes()).decode()
            html = html.replace(f'src="{relative}"', f'src="data:image/png;base64,{png}"')
    (output / "SUMMARY.html").write_text(html_page(html))
    for folder in ("historical_data_checks", "historical_garch", "garch_checks"):
        path = output / folder / "SUMMARY.md"
        if path.is_file():
            rendered = markdown(path.read_text(), extensions=["tables", "fenced_code"])
            path.with_suffix(".html").write_text(html_page(rendered))


def html_page(html):
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Research verification</title>
<style>body{font:17px/1.55 system-ui,sans-serif;max-width:1050px;margin:36px auto;padding:0 24px;color:#172b3a}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:9px;border:1px solid #cad5dc;text-align:left}
th{background:#edf3f7}img{max-width:100%}pre{overflow:auto;background:#f2f5f7;padding:16px}a{color:#075c9b}
h1,h2{line-height:1.2}h2{margin-top:32px}</style><body>""" + html + "</body></html>"


def verify_existing(output):
    manifest = json.loads((output / "manifest.json").read_text())
    for relative, expected in manifest["outputs"].items():
        path = output / relative
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Saved output changed or missing: {relative}")
    for path, expected in manifest["inputs"].items():
        if not Path(path).is_file() or digest(path) != expected:
            raise ValueError(f"Input changed or missing: {path}")
    if source_hashes() != manifest["source_sha256"]:
        raise ValueError("Source or configuration changed after verification")
    return len(manifest["outputs"])


def snapshot_source(output, hashes):
    with zipfile.ZipFile(output / "source_snapshot.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for relative, expected in hashes.items():
            content = (PROJECT_ROOT / relative).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"Source changed while snapshotting: {relative}")
            archive.writestr(relative, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify-existing", type=Path)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DATA_DIR)
    args = parser.parse_args()
    if args.verify_existing is not None:
        count = verify_existing(args.verify_existing.resolve())
        print(f"PASS: {count} output hashes, all supplied input hashes, and source/configuration match.")
        return 0
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Use a new output directory; verification records are never overwritten")
    code = source_hashes()
    output.mkdir(parents=True)
    snapshot_source(output, code)
    summary, tables = audit_inputs(args.raw_dir.resolve(), output / "input_audit")
    checks = verification_checks(output, summary, args.raw_dir.resolve())
    inventory = tables["input_inventory"]
    inputs = dict(zip(inventory.path, inventory.sha256, strict=True))
    for row in tables["daily_file_readiness"].itertuples():
        if row.exists:
            inputs[row.path] = row.sha256
    if source_hashes() != code or any(digest(p) != h for p, h in inputs.items()):
        raise ValueError("Inputs or source changed during verification; results are not sealed")
    publish(output, summary_body(summary, tables, checks, output))
    manifest = {"created_utc": datetime.now(UTC).isoformat(), "source_sha256": code,
                "inputs": inputs, "status": "verified_with_data_blockers" if
                checks["passed"] and summary["input_audit_passed"] else "failed",
                "real_data_garch_status": summary["real_data_garch_status"],
                "versions": {"python": platform.python_version(), **{
                    p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy", "pytest")}},
                "outputs": {str(p.relative_to(output)): digest(p)
                            for p in sorted(output.rglob("*")) if p.is_file()}}
    write_json(output / "manifest.json", manifest)
    print(f"Readable report: {output / 'SUMMARY.html'}")
    print(f"Real-data daily GARCH: {summary['real_data_garch_status']}")
    return 0 if checks["passed"] and summary["input_audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
