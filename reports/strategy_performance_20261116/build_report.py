"""Recompute archived conditional metrics; never fit or score a new strategy.

Run from the repository root. Existing output directories are immutable.
"""

import argparse
import hashlib
import html
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ARCHIVE = Path("reports/hrp_timing_sensitivity_20261113")
VERIFICATION = Path("reports/research_verification_20261116")
TOLERANCE = 1e-10
LABEL = "ARCHIVED CONDITIONAL RESULTS — NO CORRECTED/FULL-SAMPLE RUN"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def independent_metrics(ledger):
    r = ledger.net_return.to_numpy(float)
    wealth = np.cumprod(1 + r)
    annual_vol = float(np.std(r, ddof=1) * np.sqrt(12))
    annual_mean = float(np.mean(r) * 12)
    return {
        "months": len(r), "mean_monthly": float(np.mean(r)),
        "std_monthly": float(np.std(r, ddof=1)), "mean_ann": annual_mean,
        "vol_ann": annual_vol, "zero_rate_mean_vol_ratio": annual_mean / annual_vol,
        "sharpe": annual_mean / annual_vol,
        "cagr": float(wealth[-1] ** (12 / len(r)) - 1),
        "cumulative_return": float(wealth[-1] - 1),
        "max_drawdown": float(np.min(wealth / np.maximum(1, np.maximum.accumulate(wealth)) - 1)),
        "worst_month": float(np.min(r)), "best_month": float(np.max(r)),
        "hit_rate_monthly": float(np.mean(r > 0)),
        "turnover_ann": float(ledger.turnover.mean() * 12),
        "mean_cost_ann": float(ledger.cost.mean() * 12),
        "cost_cash_per_initial_capital": float(ledger.cost_cash.sum()),
        "avg_gross_exposure": float(ledger.gross_exposure.mean()),
    }


def check_ledger(ledger, lag, portfolio):
    calendar = pd.period_range("1976-01", "2014-12", freq="M")
    if not ledger.index.equals(calendar):
        raise ValueError(f"Incorrect or incomplete calendar: lag {lag}, {portfolio}")
    required = ["net_return", "gross_return", "cost", "turnover", "nav_start", "nav_end"]
    if not np.isfinite(ledger[required].to_numpy(float)).all():
        raise ValueError("Nonfinite required ledger values")
    np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost,
                               rtol=0, atol=TOLERANCE)
    np.testing.assert_allclose(ledger.cost, ledger.turnover * 0.0002, rtol=0, atol=TOLERANCE)
    np.testing.assert_allclose(ledger.nav_end, ledger.nav_start * (1 + ledger.net_return),
                               rtol=0, atol=TOLERANCE)
    np.testing.assert_allclose(ledger.nav_start.iloc[1:], ledger.nav_end.iloc[:-1],
                               rtol=0, atol=TOLERANCE)
    np.testing.assert_allclose(ledger.nav_start.iloc[0], 1.0, rtol=0, atol=TOLERANCE)
    if ledger.gross_limit_breach.any() or ledger.risk_limit_breach.any():
        raise ValueError("Archived ledger contains a declared limit breach")
    return {"information_lag_months": lag, "portfolio": portfolio, "months": len(ledger),
            "calendar": "PASS", "net_accounting": "PASS", "cost_accounting": "PASS",
            "nav_accounting": "PASS", "declared_limit_flags": "PASS"}


def archived_results(root):
    expected = pd.read_csv(root / ARCHIVE / "metrics.csv").set_index(
        ["information_lag_months", "portfolio"]
    )
    rows, checks = [], []
    for lag in (1, 2):
        for portfolio in ("baseline", "enhanced"):
            path = root / ARCHIVE / f"lag{lag}_{portfolio}_ledger.csv.gz"
            ledger = pd.read_csv(path, index_col=0)
            ledger.index = pd.PeriodIndex(ledger.index, freq="M")
            check = check_ledger(ledger, lag, portfolio)
            stats = independent_metrics(ledger)
            error = max(abs(stats[key] - expected.loc[(lag, portfolio), key]) for key in stats)
            if error > TOLERANCE:
                raise ValueError(f"Archived metric mismatch: lag {lag}, {portfolio}: {error}")
            check.update(metrics_match="PASS", max_metric_absolute_error=error)
            checks.append(check)
            rows.append({"information_lag_months": lag, "portfolio": portfolio,
                         "result_status": "ARCHIVED_CONDITIONAL_PRE_FIX", **stats})
    return pd.DataFrame(rows), pd.DataFrame(checks)


def readiness():
    return pd.DataFrame([
        {"period": "1976-01–2025-05", "requested_run": "Corrected full available strategy sample",
         "status": "NOT_COMPLETED_BLOCKED", "performance_available": False,
         "reason": "Daily prices end 2014-12; historical endpoint gaps remain unresolved."},
        {"period": "1976-01–2014-12", "requested_run": "Corrected historical comparison",
         "status": "NOT_COMPLETED", "performance_available": False,
         "reason": "Current corrected strategy has not completed a full historical backtest; endpoint policy unresolved."},
        {"period": "2015-01–2025-05", "requested_run": "Post-development comparison",
         "status": "BLOCKED_NO_DAILY_EXTENSION", "performance_available": False,
         "reason": "Actual input preflight rejects insufficient daily coverage; monthly returns also contain gaps."},
        {"period": "1976-01–2014-12", "requested_run": "Archived conditional comparison",
         "status": "ARCHIVED_PRE_FIX_ONLY", "performance_available": True,
         "reason": "Four old ledgers independently reconciled; source/risk/data assumptions predate repairs."},
    ])


def input_records(root, preflight_path):
    official = json.loads((root / VERIFICATION / "manifest.json").read_text())
    inputs = {str(Path(name).relative_to(root)): expected for name, expected in official["inputs"].items()}
    extras = list((root / ARCHIVE).glob("*"))
    extras += [root / VERIFICATION / "manifest.json", root / VERIFICATION / "input_audit/summary.json",
               root / VERIFICATION / "input_audit/daily_endpoint_evidence.csv"]
    for path in extras:
        if path.is_file():
            inputs[str(path.relative_to(root))] = digest(path)
    for name, expected in inputs.items():
        if digest(root / name) != expected:
            raise ValueError(f"Input changed from verification: {name}")
    return inputs, digest(preflight_path)


def display_table(metrics):
    rows = []
    for row in metrics.itertuples(index=False):
        rows.append({
            "Lag": f"{row.information_lag_months} month" + (" (primary)" if row.information_lag_months == 1 else "s (sensitivity)"),
            "Portfolio": "Inverse-vol baseline" if row.portfolio == "baseline" else "Within-class HRP",
            "Net mean / yr": f"{row.mean_ann:.2%}", "CAGR": f"{row.cagr:.2%}",
            "Volatility / yr": f"{row.vol_ann:.2%}", "Sharpe (RF=0)": f"{row.sharpe:.3f}",
            "Max drawdown": f"{row.max_drawdown:.2%}", "Turnover / yr": f"{row.turnover_ann:.2f}×",
            "Cost / yr": f"{row.mean_cost_ann:.2%}", "Positive months": f"{row.hit_rate_monthly:.1%}",
        })
    return pd.DataFrame(rows)


def markdown_table(frame):
    headings = "| " + " | ".join(frame.columns) + " |"
    rule = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = ["| " + " | ".join(map(str, row)) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join([headings, rule, *rows])


def paragraphs():
    return [
        ("No corrected strategy run through May 2025 has been completed. The table below contains old, conditional "
        "1976–2014 results recalculated from archived ledgers. This report does not run a strategy or produce new out-of-sample scores."),
        ("Both archived arms use class-specific trend signals, DCC-GARCH risk with a shared inverse-volatility shadow "
        "rescale, 10% trading bands, 2 bps ordinary costs and zero cash interest. The baseline sizes by inverse volatility; "
        "the enhancement uses signed HRP within each asset class. Only the sizing comparison is isolated here; this is not a test of GARCH versus rolling covariance."),
        ("These archived forecasts predate the repairs to RL/ER daily source consistency, missing daily observations, "
        "excluded-market risk estimation, optimizer failure handling and calibration timing. March 1997 returns for DT, GS, LX and SS "
        "use an unverified endpoint assumption. The archived monthly panel also accepts HS January/February 2006 returns "
        "that the current strict daily-endpoint rule leaves unknown. Recomputing statistics does not repair those forecasts or assumptions."),
        ("The full monthly workbook spans February 1969–May 2025 (676 months, 58 markets). The restored daily files end in "
        "December 2014. The 125 post-2014 monthly calendar slots cannot reconstruct the daily innovations "
        "required by this GARCH model; there are also 226 missing market-month cells in that newer period."),
        ("The actual matched-runner input preflight for January 2015–May 2025 stopped before fitting or scoring: "
        "'Price coverage must span at least 2006-11 through 2025-05'. The saved declaration uses a January 2010 shadow start. "
        "This is a readiness check, not an attempted or completed historical backtest."),
        ("The archived primary lag-1 HRP Sharpe is higher, but turnover is higher. At lag 2 the HRP Sharpe is lower and "
        "the maximum drawdown is worse. These are inspected development results and do not establish a reliable enhancement or an independent out-of-sample advantage."),
    ]


def methodology():
    return [
        ("Annual net mean = 12 × mean monthly net return; volatility = √12 × sample standard deviation. "
        "Sharpe uses zero RF and equals annual mean / annual volatility. No missing months are dropped."),
        ("CAGR compounds monthly net returns over 468 calendar months. Maximum drawdown includes the initial NAV of 1. "
        "Annual turnover and cost are 12 × their monthly arithmetic means; one-way absolute turnover is not halved."),
        ("Costs include 2 bps × turnover, including recorded entries, source transitions and terminal liquidation. "
        "Regular futures rolls, bid/ask histories and executable fills remain unverified. Positive-month rate includes all 468 months, including flat months."),
        ("All four ledgers passed the complete January 1976–December 2014 calendar, net = gross − cost, "
        "cost = turnover × 0.0002, NAV continuity and declared limit-flag checks. All independently recomputed archived "
        "metric fields match metrics.csv within absolute tolerance 1e-10. These checks verify archived arithmetic, not data provenance or current-model performance."),
    ]


def commands():
    script = "reports/strategy_performance_20261116/build_report.py"
    return (f".venv/bin/python {script} --verify-existing reports/strategy_performance_20261116\n\n"
            f".venv/bin/python {script} --output reports/my_strategy_performance")


def write_reports(output, metrics, ready):
    table = display_table(metrics)
    intro, methods = paragraphs(), methodology()
    md = ["# Strategy performance: current status and archived context", "", f"**{LABEL}**", ""]
    md += [intro[0], "", "## Available archived table", "", "January 1976–December 2014; 468 months in every row.", "",
           markdown_table(table), "", *[line for paragraph in intro[1:] for line in (paragraph, "")]]
    md += ["## Run readiness", "", markdown_table(ready), "", "## Definitions and checks", ""]
    md += [line for paragraph in methods for line in (paragraph, "")]
    md += ["## Reproduce or verify", "", "Run from the repository root. Use a new output directory.", "",
           "```sh", commands(), "```", "", ("See checks.csv, archived_metrics.csv, run_readiness.csv, "
           "full_sample_preflight.json and provenance.json. manifest.json records input/output hashes.")]
    (output / "SUMMARY.md").write_text("\n".join(md) + "\n")
    write_html(output, table, ready, intro, methods)


def write_html(output, table, ready, intro, methods):
    p = lambda value: "<p>" + html.escape(value) + "</p>"
    content = ["<h1>Strategy performance</h1>", f'<div class="notice">{html.escape(LABEL)}</div>',
               p(intro[0]), "<h2>Available archived table</h2>", p("January 1976–December 2014; 468 months in every row."),
               '<div class="table">' + table.to_html(index=False, escape=True, border=0) + "</div>"]
    content += [p(value) for value in intro[1:]]
    content += ["<h2>Run readiness</h2>", '<div class="table">' + ready.to_html(index=False, escape=True, border=0) + "</div>",
                "<h2>Definitions and checks</h2>", *[p(value) for value in methods],
                "<h2>Reproduce or verify</h2>", p("Run from the repository root. Use a new output directory."),
                "<pre>" + html.escape(commands()) + "</pre>",
                ('<p><a href="archived_metrics.csv">Metrics CSV</a> · <a href="checks.csv">Checks</a> · '
                '<a href="run_readiness.csv">Run readiness</a> · <a href="full_sample_preflight.json">Actual preflight</a> · '
                '<a href="provenance.json">Provenance</a> · <a href="manifest.json">Hash manifest</a></p>')]
    css = "body{font:16px/1.6 system-ui,sans-serif;margin:32px auto;max-width:1400px;padding:0 24px;color:#1b2934}"
    css += ".notice{background:#fff0cf;border-left:6px solid #a66500;padding:16px;font-weight:700}"
    css += "h1,h2{line-height:1.25}table{border-collapse:collapse;font-size:14px;width:100%}.table{overflow:auto}"
    css += "td,th{border-bottom:1px solid #ccd5dc;padding:10px;text-align:right}td:nth-child(-n+2),th:nth-child(-n+2){text-align:left}"
    css += "thead{background:#edf2f6}pre{padding:18px;background:#edf2f6;overflow:auto}a{color:#12598b}"
    document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    document += "<title>Strategy performance — archived conditional results</title><style>" + css + "</style><body>"
    (output / "SUMMARY.html").write_text(document + "\n".join(content) + "</body></html>\n")


def verify_existing(root, output):
    manifest_path = output / "manifest.json"
    if digest(manifest_path) != (output / "manifest.sha256").read_text().strip():
        raise ValueError("Report manifest hash changed")
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["inputs"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Report input changed: {name}")
    for name, expected in manifest["outputs"].items():
        if digest(output / name) != expected:
            raise ValueError(f"Report output changed: {name}")
    print(f"PASS: {len(manifest['inputs'])} input hashes and {len(manifest['outputs'])} output hashes match.")


def build(root, output, preflight_path):
    if output.exists():
        raise ValueError("Use a new output directory; previous reports must be preserved")
    if not (root / "src/backtest/performance.py").is_file():
        raise ValueError("Run from the managed_futures repository root")
    inputs, preflight_hash = input_records(root, preflight_path)
    metrics, checks = archived_results(root)
    preflight = json.loads(preflight_path.read_text())
    if preflight.get("status") != "BLOCKED" or preflight.get("monthly_end") != "2025-05":
        raise ValueError("Expected the saved blocked full-sample input preflight")
    output.mkdir(parents=True)
    shutil.copy2(Path(__file__), output / "build_report.py")
    shutil.copy2(preflight_path, output / "full_sample_preflight.json")
    metrics.to_csv(output / "archived_metrics.csv", index=False, float_format="%.17g")
    checks.to_csv(output / "checks.csv", index=False, float_format="%.17g")
    ready = readiness()
    ready.to_csv(output / "run_readiness.csv", index=False)
    write_reports(output, metrics, ready)
    provenance = {"created_utc": datetime.now(UTC).isoformat(), "status": LABEL,
                  "new_strategy_backtest_performed": False, "independent_oos_score_performed": False,
                  "archive": str(ARCHIVE), "verification": str(VERIFICATION),
                  "preflight_sha256": preflight_hash, "metric_absolute_tolerance": TOLERANCE,
                  "raw_input_count": 66, "archived_cases_checked": 4, "months_per_case": 468}
    write_json(output / "provenance.json", provenance)
    outputs = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()}
    write_json(output / "manifest.json", {"inputs": inputs, "outputs": outputs, "status": LABEL})
    (output / "manifest.sha256").write_text(digest(output / "manifest.json") + "\n")
    verify_existing(root, output)
    print(display_table(metrics).to_string(index=False))
    print(f"Readable report: {output / 'SUMMARY.html'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify-existing", type=Path)
    parser.add_argument("--preflight-record", type=Path,
                        default=Path(__file__).resolve().parent / "full_sample_preflight.json")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.verify_existing:
        verify_existing(root, args.verify_existing.resolve())
    else:
        build(root, args.output.resolve(), args.preflight_record.resolve())


if __name__ == "__main__":
    main()
