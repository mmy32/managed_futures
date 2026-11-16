"""Readable tables and figures for the declared monthly full-sample comparison."""

import base64
import html
import json
from pathlib import Path

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

RISK_NAMES = {"rolling": "Rolling covariance", "monthly_dcc_garch": "Monthly DCC-GARCH"}
PORTFOLIO_NAMES = {"inverse_vol": "Inverse volatility", "hrp_within_class": "Within-class HRP"}
PERIOD_NAMES = {
    "in_sample": "Development: January 1976–December 2014",
    "test_period": "Test calendar: January 2015–May 2025",
    "full_sample": "Combined: January 1976–May 2025",
}
NOTICE = (
    "COVERAGE-CONDITIONED RESEARCH RESULTS: the market set uses availability through May 2025. "
    "The 2015–2025 test calendar is not an untouched out-of-sample universe."
)


def _display_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in metrics.itertuples(index=False):
        rows.append({
            "Period": PERIOD_NAMES[row.period],
            "Risk model": RISK_NAMES[row.risk_model],
            "Sizing": PORTFOLIO_NAMES[row.portfolio],
            "Months": int(row.months),
            "Annual net mean": f"{row.mean_ann:.2%}",
            "CAGR": f"{row.cagr:.2%}",
            "Annual volatility": f"{row.vol_ann:.2%}",
            "Sharpe (RF=0)": f"{row.sharpe:.3f}",
            "Maximum drawdown": f"{row.max_drawdown:.2%}",
            "Annual turnover": f"{row.turnover_ann:.2f}×",
            "Annual cost": f"{row.mean_cost_ann:.2%}",
            "Positive months": f"{row.hit_rate_monthly:.1%}",
        })
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    rule = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = ["| " + " | ".join(map(str, row)) + " |"
            for row in frame.itertuples(index=False, name=None)]
    return "\n".join([header, rule, *rows])


def _coverage_context(audit: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    count = int(audit.included_coverage.sum())
    omitted = audit.loc[~audit.included_coverage].reset_index()
    columns = [omitted.columns[0], "missing_after_first", "exclusion_reason"]
    omitted = omitted[columns].rename(columns={columns[0]: "Market",
        "missing_after_first": "Missing months after first observation",
        "exclusion_reason": "Reason"})
    text = (
        f"The conditional run uses {count} fixed markets with uninterrupted supplied returns "
        "from their first observation through May 2025. Leading pre-inception blanks are "
        "allowed; markets enter only after the common prior-history requirements are met. "
        "Selection uses the full file's availability, so survivorship and availability "
        "selection can affect all reported comparisons. Return magnitudes do not select markets."
    )
    return text, omitted


def _start_context(status: dict) -> str:
    text = (
        "All declared calendar months remain in the ledgers, including any initially flat "
        "months when fewer than 10 markets meet the common history requirements. The strategy "
        "holds zero exposure until ready; no threshold or start date is changed to force activity."
    )
    active = status.get("first_active_months", {})
    if active:
        text += " First active months: " + "; ".join(
            f"{name}: {month}" for name, month in active.items()
        ) + "."
    count = status.get("eligible_at_start", status.get("start_eligible"))
    if count is not None:
        text += f" Eligible markets at the declared start: {count}."
    return text


def _methodology() -> list[str]:
    return [
        ("Only the professor's full monthly-return workbook and asset map supply market inputs. "
        "The workbook's RL series is used as supplied, with no reconstruction or daily ER override. "
        "No missing return is filled, and no portfolio month is dropped."),
        ("The four variants cross rolling covariance or monthly DCC-GARCH with inverse-volatility "
        "or signed within-class HRP sizing. All use the same eligibility set, 36 complete prior "
        "monthly observations and at least 60 observations available at the annual GARCH fit. "
        "The minimum portfolio universe is 10 markets. Eligibility and forecasts use past inputs."),
        ("GARCH and DCC parameters are estimated at monthly frequency on expanding past data, "
        "refitted annually using the prior December cutoff. The next-month covariance is "
        "annualized by 12; daily parameters and 21-day aggregation are not used. This is a new "
        "monthly specification, not a replication of the archived daily-GARCH strategy."),
        ("Shared controls are 10% correlation shrinkage, a 2% annual instrument-volatility floor, "
        "3× gross exposure cap, 10% forecast annual portfolio-risk ceiling, 10% trading band and "
        "2 bps per unit of absolute one-way traded notional. Cash interest is zero. The baseline "
        "rescale is estimated from each risk model's inverse-volatility shadow portfolio using "
        "60 prior calendar months with at least 24 valid observations, then shared with its HRP arm."),
        ("Signals use the sign of the preceding 12-month return sum for commodities, fixed income "
        "and equity indices. FX blends the 3-month and 12-month signals. Monthly decisions use "
        "information through the previous month; fills at the previous endpoint are idealized."),
        ("Each variant runs as one continuous portfolio from January 1976 through May 2025. "
        "The development and test tables summarize slices of that ledger. Holdings, risk "
        "calibration and NAV continue across December 2014; there is no restart or liquidation "
        "there. Initial entry and May 2025 liquidation costs belong to their actual ledger months."),
        ("Annual net mean is 12 times the monthly arithmetic mean; annual volatility is the "
        "monthly sample standard deviation times √12. Sharpe is annual net mean divided by "
        "annual volatility with RF=0. CAGR compounds returns over the stated calendar. Drawdown "
        "is rebased at the start of each displayed period; turnover and cost are 12 times their "
        "monthly means. Subperiod CAGR is a return summary, not a separately executed account."),
        ("The 2015–May 2025 rows are a chronological test of fixed rules with sequential past-only "
        "updates. The full-sample coverage rule and prior inspection of this dataset prevent "
        "calling them independently untouched out-of-sample evidence. Differences are descriptive; "
        "this table alone does not establish a statistically reliable or executable advantage."),
    ]


def _plot_ledgers(output: Path) -> str:
    fig = Figure(figsize=(11, 8))
    FigureCanvasAgg(fig)
    axes = fig.subplots(2, 1, sharex=True)
    for risk, risk_name in RISK_NAMES.items():
        for portfolio, portfolio_name in PORTFOLIO_NAMES.items():
            path = output / f"{risk}_{portfolio}_ledger.csv.gz"
            ledger = pd.read_csv(path, index_col=0)
            index = pd.PeriodIndex(ledger.index, freq="M").to_timestamp("M")
            wealth = (1 + ledger.net_return).cumprod()
            label = f"{risk_name} / {portfolio_name}"
            axes[0].plot(index, wealth.to_numpy(), label=label, linewidth=1.4)
            drawdown = wealth / wealth.cummax().clip(lower=1) - 1
            axes[1].plot(index, 100 * drawdown.to_numpy(), linewidth=1.2)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Growth of 1, log scale")
    axes[0].set_title("Monthly strategy comparison — conditional on full-sample coverage")
    axes[0].legend(fontsize=8, loc="upper left")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_xlabel("Year; dashed line marks January 2015")
    for ax in axes:
        ax.axvline(pd.Timestamp("2015-01-01"), color="#555555", linestyle="--", linewidth=1)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    name = "equity_and_drawdown.png"
    fig.savefig(output / name, dpi=160)
    fig.clear()
    return name


def _strict_table(status: dict) -> pd.DataFrame:
    rows = status.get("strict_checks", [])
    if not rows:
        return pd.DataFrame([{"Case": "All-market check", "Status": "Not recorded",
                              "Error": "Read status.json before interpreting completeness."}])
    table = pd.DataFrame(rows)
    return table.rename(columns={"case": "Case", "status": "Status", "error": "Error"})


def _commands() -> str:
    return (
        "PYTHONPATH=. .venv/bin/python scripts/run_monthly_full_sample.py "
        "--verify-existing reports/monthly_full_sample_20261116\n\n"
        "PYTHONPATH=. .venv/bin/python scripts/run_monthly_full_sample.py "
        "--output reports/my_monthly_run"
    )


def _write_markdown(output, display, context, omitted, strict, chart):
    lines = ["# Monthly full-sample strategy results", "", f"**{NOTICE}**", "", context, ""]
    for title in PERIOD_NAMES.values():
        table = display[display.Period.eq(title)].drop(columns="Period")
        lines += [f"## {title}", "", _markdown_table(table), ""]
    lines += [f"![Conditional equity and drawdown curves]({chart})", "",
              "## Strict all-market check", "", _markdown_table(strict), "",
              ("An unknown return on an existing holding stops that attempt. The conditional "
              "table does not repair or substitute values for the omitted markets."), "",
              "## Omitted markets", "", _markdown_table(omitted), "",
              "## Method and interpretation", ""]
    for paragraph in _methodology():
        lines += [paragraph, ""]
    lines += ["## Verify or reproduce", "", "Run from the repository root; use a new output directory.",
              "", "```sh", _commands(), "```", "", ("See metrics.csv for unrounded values, "
              "checks.csv for verification, model_parameters.csv for actual fitted parameters, "
              "universe_audit.csv for coverage and status.json for the complete run status."), ""]
    (output / "SUMMARY.md").write_text("\n".join(lines))


def _paragraph(value: str) -> str:
    return "<p>" + html.escape(value) + "</p>"


def _html_table(frame: pd.DataFrame) -> str:
    return '<div class="table">' + frame.to_html(index=False, escape=True, border=0) + "</div>"


def _artifact_links(output: Path) -> str:
    names = ["metrics.csv", "metrics_display.csv", "checks.csv", "model_parameters.csv",
             "universe_audit.csv", "status.json", "equity_and_drawdown.png", "SUMMARY.md"]
    return "<p>" + " · ".join(f'<a href="{name}">{html.escape(name)}</a>'
                                for name in names if (output / name).exists()) + "</p>"


def _write_html(output, display, context, omitted, strict, chart):
    content = ["<h1>Monthly full-sample strategy results</h1>",
               '<div class="notice">' + html.escape(NOTICE) + "</div>", _paragraph(context)]
    for title in PERIOD_NAMES.values():
        table = display[display.Period.eq(title)].drop(columns="Period")
        content += ["<h2>" + html.escape(title) + "</h2>", _html_table(table)]
    encoded = base64.b64encode((output / chart).read_bytes()).decode("ascii")
    content += [f'<img alt="Conditional monthly equity and drawdown curves" src="data:image/png;base64,{encoded}">',
                "<h2>Strict all-market check</h2>", _html_table(strict),
                _paragraph("An unknown return on an existing holding stops that attempt. The conditional "
                           "table does not repair or substitute values for the omitted markets."),
                "<h2>Omitted markets</h2>", _html_table(omitted), "<h2>Method and interpretation</h2>"]
    content += [_paragraph(value) for value in _methodology()]
    content += ["<h2>Verify or reproduce</h2>",
                _paragraph("Run from the repository root; use a new output directory."),
                "<pre>" + html.escape(_commands()) + "</pre>", _artifact_links(output)]
    css = "body{font:16px/1.6 system-ui,sans-serif;max-width:1450px;margin:32px auto;padding:0 24px;color:#1d2934}"
    css += ".notice{padding:16px;background:#fff1cf;border-left:6px solid #a76b00;font-weight:700}"
    css += ".table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}"
    css += "td,th{padding:9px;border-bottom:1px solid #ced8df;text-align:right}td:first-child,th:first-child{text-align:left}"
    css += "thead{background:#edf2f6}img{width:100%;height:auto}pre{padding:18px;background:#edf2f6;overflow:auto}a{color:#12598b}"
    document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    document += "<title>Monthly full-sample strategy results</title><style>" + css + "</style><body>"
    (output / "SUMMARY.html").write_text(document + "\n".join(content) + "</body></html>\n")


def write_readable_report(output: Path) -> None:
    """Render the runner's exported results without changing its data or accounting."""
    output = Path(output)
    metrics = pd.read_csv(output / "metrics.csv")
    audit = pd.read_csv(output / "universe_audit.csv", index_col=0)
    status = json.loads((output / "status.json").read_text())
    display = _display_metrics(metrics)
    display.to_csv(output / "metrics_display.csv", index=False)
    context, omitted = _coverage_context(audit)
    context += " " + _start_context(status)
    strict = _strict_table(status)
    chart = _plot_ledgers(output)
    _write_markdown(output, display, context, omitted, strict, chart)
    _write_html(output, display, context, omitted, strict, chart)
