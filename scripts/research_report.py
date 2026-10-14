"""Presentation formatting only; calculations live in src/backtest."""

import hashlib
import json
import os
import re

os.environ.setdefault("MPLCONFIGDIR", "/tmp/qps-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter

from src.backtest.attribution import CLASS_NAMES
from src.backtest.sample_diagnostics import risk_diagnostics
from src.config import DOCS_DIR, PROJECT_ROOT, QPS_OUTPUT_DIR, QPS_REPORT_DIR

ROOT = PROJECT_ROOT
OUT = QPS_OUTPUT_DIR / "risk"
COLORS = ["#2676a5", "#ce7c27", "#358574", "#9563a5"]


def save(fig, name, out):
    fig.savefig(out / f"{name}.png", dpi=150)
    plt.close(fig)


def style(axis, percent=False):
    axis.grid(alpha=0.2)
    if percent:
        axis.yaxis.set_major_formatter(PercentFormatter(1))


def make_charts(classes, counts, autocorr, ledgers, settings, out=OUT):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    conditional = (
        "Conditional March 1997 endpoint assumption" if out.name == "endpoint_sensitivity" else ""
    )
    dates = classes.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.stackplot(
        dates,
        *[counts[c] for c in CLASS_NAMES],
        labels=list(CLASS_NAMES.values()),
        colors=COLORS,
        alpha=0.85,
    )
    ax.axhline(10, color="black", linestyle="--", label="Portfolio minimum: 10")
    ax.set(
        title="Prior-eligible instruments • January 1976–December 2014", ylabel="Instrument count"
    )
    ax.legend(ncol=3, fontsize=9, loc="upper left")
    style(ax)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, "eligible_counts", out)

    fig, ax = plt.subplots(figsize=(11, 4.5), layout="constrained")
    for (group, s), color in zip(classes.items(), COLORS):
        # Missing class history is not filled with a zero return.
        cumulative = (
            (1 + s.loc[s.first_valid_index() :]).cumprod(skipna=False) - 1 if s.notna().any() else s
        )
        ax.plot(cumulative.index.to_timestamp(), cumulative, label=CLASS_NAMES[group], color=color)
    ax.set(
        title="Equal-weight classes • compound from first eligible month, stop at any unknown return",
        ylabel="Cumulative return (unscaled, before costs)",
    )
    ax.legend(ncol=2, fontsize=9)
    style(ax, True)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, "class_cumulative", out)

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout="constrained", sharex=True, sharey=True)
    for ax, (group, name), color in zip(axes.flat, CLASS_NAMES.items(), COLORS):
        q = autocorr[autocorr.asset_class.eq(group)]
        ax.errorbar(
            q.lag,
            q.rho,
            yerr=np.vstack([q.rho - q.ci_low, q.ci_high - q.rho]),
            fmt="o-",
            capsize=3,
            color=color,
            linewidth=1,
        )
        ax.axhline(0, color="gray", linewidth=1)
        ax.set(
            title=f"{name} | matched n = {q.matched_months.min()}–{q.matched_months.max()}",
            xlabel="Monthly lag",
            ylabel="Spearman correlation",
            xticks=range(1, 13),
        )
        style(ax)
    fig.suptitle(
        (conditional + "\n" if conditional else "")
        + "Monthly class-return autocorrelation • approximate 95% HAC intervals\nExploratory: 48 comparisons; HAC bandwidth equals return lag",
        fontsize=12,
    )
    save(fig, "autocorrelation", out)

    if not ledgers:
        return

    names = [("Baseline trend", "trend", COLORS[0]), ("Matching STATIC", "static", COLORS[1])]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for label, strategy, color in names:
        ledger = ledgers[f"correlated_band10_5bps_{strategy}"]
        wealth = ledger.nav_end
        axes[0].plot(dates, wealth - 1, label=label, color=color)
        axes[1].plot(dates, wealth / wealth.cummax().clip(lower=1) - 1, label=label, color=color)
    for ax, title in zip(axes, ["Compounded net returns", "Drawdowns from prior peak"]):
        ax.set_title(title)
        ax.legend(fontsize=9)
        style(ax, True)
    fig.suptitle(
        (conditional + "\n" if conditional else "")
        + "1976–2014 • 5 bps trading costs • ±10% bands • zero interest"
    )
    save(fig, "performance", out)

    fig, axes = plt.subplots(3, 1, figsize=(11, 10), layout="constrained", sharex=True)
    for label, strategy, color in names:
        ledger = ledgers[f"correlated_band10_5bps_{strategy}"]
        timeline, _ = risk_diagnostics(ledger)
        axes[0].plot(
            dates, timeline.realized_gross_vol_36m, label=f"{label}: realized gross", color=color
        )
        axes[0].plot(
            dates,
            timeline.forecast_rms_36m,
            label=f"{label}: forecast RMS",
            color=color,
            linestyle="--",
        )
        axes[1].plot(dates, timeline.gross_after_cost, label=label, color=color)
        axes[2].plot(dates, timeline.drawdown, label=label, color=color)
    axes[0].set_title("36-month realized volatility and forecasts over the same window")
    axes[1].set_title("Gross exposure / capital after rebalance costs")
    axes[1].axhline(3, color="gray", linestyle="--", label="3× rebalance cap")
    axes[2].set_title("Net drawdowns")
    for i, ax in enumerate(axes):
        style(ax, i != 1)
        ax.legend(fontsize=8, ncol=2)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, "risk", out)


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |",
        ]
        + ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    )


def validation_summary():
    record = json.loads((OUT / "validation.json").read_text())
    current = all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in record["files"].items()
    )
    return f"{record['passed']} tests pass" if current else "Validation record needs refreshing"


def _main_metrics(metrics):
    return metrics[(metrics.band == 0.1) & (metrics.cost_bps == 5)].set_index("strategy")


def _opening(assumption):
    assumption_note = (
        "**Data qualification:** results use an unverified March 1997 endpoint assumption "
        "for DT, GS, LX and SS, restoring eight March/April returns. The preserved-policy "
        "run stops on missing held returns. [Evidence](../../docs/ENDPOINT_DECISION.md) · "
        "[Data status](../../docs/DATA_STATUS.md)."
        if assumption is not None
        else ""
    )
    return f"""# Managed futures: risk-controlled trend

**Research question:** does following 12-month trends add value over staying long when both portfolios use the same risk controls and trading costs?

**Key finding:** trend improves full-sample return, Sharpe and drawdown versus the always-long benchmark. The advantage is smaller in the most recent decade, and risk forecasts understate realized fluctuations.

{assumption_note}

"""


def _data_section(audit):
    return f"""## 1. Data description

| Item | Definition |
|---|---|
| Sample | January 1976–December 2014; 468 months |
| Inputs | Monthly returns, daily futures prices and a market/class map |
| Universe | {audit["retained_columns"]} retained series across commodities, equities, fixed income and currencies |
| Preparation | Remove duplicate exposures and exclude YM/EC; apply audited endpoint rules |
| Information | Prior observations only for signals, risk estimates and RL/ER source selection |

January 1976 has {audit["eligible_at_start"]} eligible instruments, below the required {audit["minimum_required"]}, so it remains flat. Trading starts in {audit["first_investable_month"]}; earlier data initialize the estimation windows.

![Eligible instruments by asset class](output/risk/eligible_counts.png)

**Takeaway:** the opportunity set grows over time; all requested months are retained, including the initial flat month.

"""


def _class_section(class_stats):
    stats = [
        [
            r.name,
            r.instruments,
            r.months,
            f"{r.mean_ann:.2%}",
            f"{r.vol_ann:.2%}",
            f"{r.sharpe:.2f}",
        ]
        for r in class_stats.itertuples(index=False)
    ]
    return f"""## 2. Summary statistics across asset classes

**Method:** each monthly class return equally weights markets eligible before that month. These are unscaled, long-only class returns before trading costs. Compute statistics from each class portfolio, rather than averaging individual-market statistics.

{table(["Class", "Markets", "Months", "Annual mean", "Annual volatility", "Sharpe"], stats)}

Annual mean = 12 × monthly mean; annual volatility = √12 × monthly sample SD. Sharpe assumes zero cash return. Histories differ across classes; missing eligible returns are not filled or silently reweighted.

![Cumulative long-only class returns](output/risk/class_cumulative.png)

**Takeaway:** fixed income has the highest descriptive Sharpe and currencies the lowest. Unequal coverage limits direct comparisons across classes.

"""


def _autocorrelation_section(autocorr):
    rows = []
    for group, name in CLASS_NAMES.items():
        q = autocorr[autocorr.asset_class.eq(group)]
        rows.append([name, f"{int(q.p_approx.lt(0.05).sum())}/12"])
    return f"""## 3. Autocorrelation

**Question:** do stronger class returns tend to be followed by stronger returns? Compare each monthly class return with its return 1–12 months earlier using Spearman rank correlation. Calendar gaps are preserved; the chart shows approximate 95% intervals allowing for serial dependence.

![Class-return autocorrelation at monthly lags 1–12](output/risk/autocorrelation.png)

{table(["Class", "Lags with approximate p < 0.05"], rows)}

**Takeaway:** evidence of class-level persistence is limited. These 48 exploratory comparisons have no multiple-testing adjustment and do not establish the profitability or optimality of the 12-month trading signal.

"""


def _construction_section():
    return """## 4. Baseline strategy construction

1. **Direction:** go long if the previous 12 monthly returns sum to a positive number, short if negative, and flat if zero.
2. **Risk estimate:** use the previous 36 months of returns, a 2% annual volatility floor, and correlations shrunk 50% toward zero.
3. **Position size:** start with `0.40 / (eligible markets × annual volatility)`, then reduce positions proportionally to meet a **10% forecast-volatility ceiling** and **3× gross exposure cap**. The 0.40 is a sizing parameter, not a portfolio risk target.
4. **Execution:** rebalance monthly with ±10% relative trading bands. A 20% target allows an existing same-direction position between 18% and 22%. Entries, exits and reversals execute at target; hard limits override bands.

**Benchmark:** STATIC stays long using the same eligibility, risk model, limits, bands and costs. Each portfolio's own forecast risk determines its scaling.

**Takeaway:** the comparison isolates the value of trend direction under matching controls. This is a risk-controlled baseline; it scales down to a ceiling rather than scaling up to a volatility target.

"""


def _stability_text(stability):
    if stability is None:
        return ""
    recent = stability[stability.period.eq("2005–2014")].set_index("strategy")
    trend, static = recent.loc["trend"], recent.loc["static"]
    return (
        f"\n**Recent period (2005–2014):** trend CAGR is {trend.cagr:.2%} versus "
        f"STATIC's {static.cagr:.2%}; Sharpe is {trend.sharpe:.2f} versus "
        f"{static.sharpe:.2f}. The full-sample return advantage is not uniform. "
        "This is an inspected historical subsample, not a fresh holdout.\n"
    )


def _results_section(metrics, alphas, stability):
    main = _main_metrics(metrics)
    trend = main.loc["trend"]
    no_band = metrics[
        (metrics.band == 0) & (metrics.cost_bps == 5) & metrics.strategy.eq("trend")
    ].iloc[0]
    results = []
    for label, field, format_spec in [
        ("Annual arithmetic mean", "mean_ann", ".2%"),
        ("Compounded annual growth (CAGR)", "cagr", ".2%"),
        ("Net Sharpe", "sharpe", ".2f"),
        ("Maximum drawdown", "max_drawdown", ".2%"),
    ]:
        results.append(
            [label] + [format(main.loc[s, field], format_spec) for s in ["trend", "static"]]
        )
    cost_rows = [
        [f"{r.cost_bps:g}", f"{r.cagr:.2%}", f"{r.sharpe:.2f}"]
        for r in metrics[metrics.band.eq(0.1) & metrics.strategy.eq("trend")].itertuples(
            index=False
        )
    ]
    return f"""## 5. Baseline strategy results

1976–2014, net of **5 bps per unit of traded exposure**, with ±10% bands and zero cash return. CAGR measures compounded growth; maximum drawdown is the largest peak-to-trough loss.

{table(["Metric", "TREND", "STATIC"], results)}

![Compounded net returns and drawdowns](output/risk/performance.png)

**Takeaway:** trend delivers stronger full-sample growth and risk-adjusted performance, with a much smaller historical drawdown. Results are conditional and in sample.
{_stability_text(stability)}
**Cost sensitivity — TREND:**

{table(["Trading cost (bps)", "CAGR", "Sharpe"], cost_rows)}

The band reduces turnover by {1 - trend.turnover_ann / no_band.turnover_ann:.1%} versus no band. Costs cover actual trades, including entries, source switches and liquidation; historical spread, impact and roll costs remain unverified.

"""


def _risk_section(metrics, attribution):
    main = _main_metrics(metrics)
    risk = [
        [
            s.upper(),
            f"{r.vol_ann:.2%}",
            f"{r.rms_forecast_vol:.2%}",
            f"{r.avg_gross_exposure:.2f}×",
            f"{r.realized_predicted_ratio:.2f}",
        ]
        for s, r in main.iterrows()
    ]
    classes = [
        [
            CLASS_NAMES[r.asset_class],
            f"{r.net_mean_ann:.2%}",
            f"{r.avg_forecast_vol_contribution:.2%}",
        ]
        for r in attribution["trend"].itertuples(index=False)
    ]
    return f"""## 6. Baseline strategy risk characteristics

### Full-sample realized risk

{table(["Portfolio", "Realized net volatility", "RMS forecast volatility", "Average gross exposure", "Calibration ratio"], risk)}

Realized annual volatility is √12 × the SD of all 468 monthly net returns. RMS summarizes the changing annual gross-risk forecasts. Calibration measures variability after scaling each gross monthly return by its preceding forecast monthly volatility: **1 is ideal; above 1 means risk was underpredicted**.

### Risk through time

![Rolling risk, exposure and drawdowns](output/risk/risk.png)

The upper panel compares realized **gross** volatility with RMS forecasts over the same trailing 36 months. The other panels show exposure and net drawdowns. Full rolling estimates begin after 36 observations; limits apply at monthly rebalances, and exposures can drift between them.

### Where risk and returns come from

{table(["Class", "Annual net return contribution", "Average forecast-volatility contribution"], classes)}

Return and forecast-risk contributions add to their respective portfolio totals. Class volatilities do not add, and the strategy does not impose equal risk across classes.

**Takeaway:** forecasts understate realized fluctuations, and commodities contribute most of the average forecast risk. A 10% forecast ceiling is not a realized-volatility cap or a loss guarantee.

"""


def _limits_section():
    return """## 7. Conclusions and next steps

**Conclusion:** following trends improves full-sample performance versus matching STATIC in this conditional study. The recent return advantage is smaller, and risk calibration needs improvement.

1. **Verify data and execution:** resolve the March 1997 endpoints and check executable prices, roll conventions and costs.
2. **Improve risk calibration:** evaluate a more responsive estimator and deliberate class-risk budgets.
3. **Test new history:** freeze the rules and evaluate an untouched sample before forward paper trading.

**Takeaway:** the historical findings justify further testing; they do not establish future performance or superiority over a matched academic baseline.

"""


def _discussion_notes(metrics, alphas, stability, audit):
    main = _main_metrics(metrics)
    alpha = alphas[(alphas.band == 0.1) & (alphas.cost_bps == 5) & (alphas.hac_lags == 6)].iloc[0]
    costs = [
        [s.upper(), f"{r.turnover_ann:.2f}×", f"{r.mean_cost_ann:.3%}"] for s, r in main.iterrows()
    ]
    return f"""<details markdown="1">
<summary>Discussion notes and supporting evidence</summary>

- **Return comparison:** TREND/STATIC correlation is {alpha.correlation:.2f}. Annualized regression alpha is {alpha.alpha_ann:.2%}, with a 95% HAC interval of [{alpha.alpha_ci_low_ann:.2%}, {alpha.alpha_ci_high_ann:.2%}]. Alpha is 12 × the monthly intercept against STATIC; six HAC lags are used. The interval excludes strategy-selection and data-provenance uncertainty.
- **Autocorrelation uncertainty:** rank regressions use calendar-spaced Bartlett HAC scores, bandwidth equal to the return lag, n/(n−2) correction and t(n−2) intervals. [All estimates](output/risk/autocorrelation.csv).
- **Data continuity:** RL/ER is one exposure; the switch to ER in {audit["source_switch_month"]} uses history known through t−2. Class compounding starts at the first eligible month and stops at an unknown subsequent return.
- **Model scope:** the presentation covers QPS's fixed 36-month risk model, ceiling and bands. The separate academic TSMOM run uses compounded signals, daily EWMA volatility, zero costs and a different missing-return policy; its results are not a matched comparison.

{table(["Portfolio", "Annual turnover / capital", "Annual direct cost drag"], costs)}

**Validation:** {validation_summary()}; the archived 2000–2014 replay matches all 12 saved runs. Validation checks accounting and timing, not vendor accuracy or executable fills.

[Methods](../../docs/RISK_METHODS.md) · [Validation](../../docs/VALIDATION.md) · [Code guide](../../docs/CODE_GUIDE.md) · [All cost scenarios](output/risk/comparison.csv) · [Historical subsamples](output/risk/stability.csv) · [Class attribution](output/risk/trend_class_attribution.csv).

Reproduce: `python scripts/run_research.py --endpoint-sensitivity`. HTML embeds all five figures.

</details>
"""


def write_report(
    metrics,
    alphas,
    class_stats,
    autocorr,
    attribution,
    audit,
    settings,
    base,
    out=OUT,
    report_path=QPS_REPORT_DIR / "REPORT.md",
    assumption=None,
    stability=None,
):
    """A concise report; calculation details and audit evidence remain linked appendices."""
    report = "".join(
        [
            _opening(assumption),
            _data_section(audit),
            _class_section(class_stats),
            _autocorrelation_section(autocorr),
            _construction_section(),
            _results_section(metrics, alphas, stability),
            _risk_section(metrics, attribution),
            _limits_section(),
            _discussion_notes(metrics, alphas, stability, audit),
        ]
    )
    report = report.replace("output/risk/", str(out.relative_to(QPS_REPORT_DIR)) + "/")
    report_path.write_text(report)
    if assumption is not None:
        # Keep the earlier filename as a compatible copy of the main presentation.
        (QPS_REPORT_DIR / "ENDPOINT_SENSITIVITY.md").write_text(report)


def docs_link(link):
    """Re-point a report-relative link so it resolves from docs/."""
    if link.startswith(("https://", "http://", "#")):
        return link
    if link.startswith("../../docs/"):
        return link[len("../../docs/") :]
    if link.startswith(("output/", "ENDPOINT_SENSITIVITY")):
        return "../" + str(QPS_REPORT_DIR.relative_to(PROJECT_ROOT)) + "/" + link
    return "../" + link


def write_blocked_report(class_stats, autocorr, audit, failures):
    rows = [[f["strategy"].upper(), f["error"]] for f in failures]
    report = f"""# Preserved data policy: status and endpoint issue

**The 1976–2014 comparison stops on missing held returns.** The simulator preserves the existing endpoint rules and fails explicitly; full-period portfolio metrics are unavailable under this policy.

For the completed, clearly labeled conditional research, read [ENDPOINT_SENSITIVITY.md](ENDPOINT_SENSITIVITY.md) or [offline HTML](ENDPOINT_SENSITIVITY.html). That report uses March 27 as an unverified March 1997 endpoint for four instruments.

## What blocks evaluation

{table(["Portfolio", "Simulator failure"], rows)}

DT, GS and LX are held in March 1997. Their last March observation is March 27, four calendar days before the March 31 target. The preserved three-day freshness rule rejects it, leaving March and April returns missing. SS has the same gap but is ineligible then. Historical venue closure and vendor identity remain unverified.

The [candidate return table](output/risk/proposed_endpoint_returns.csv) contains the eight implied March/April returns. They are not applied to primary inputs. The separate sensitivity uses exact observed closes in a copy of the return matrix, then recomputes the full trading path. [Evidence and decision note](../../docs/ENDPOINT_DECISION.md).

## Sample and validation

The requested 468 months remain January 1976–December 2014. January 1976 has {audit["eligible_at_start"]} eligible instruments versus the required {audit["minimum_required"]}, so it is flat. First trading month: {audit["first_investable_month"]}.

{validation_summary()}. The archived 2000–2014 refactor replay is independent of the endpoint sensitivity. [Validation record](output/risk/validation.json) · [Sample audit](output/risk/sample_audit.json) · [Run status](output/risk/run_status.json).

## Reproduce

- `python scripts/run_research.py`: preserves the data policy, refreshes this status report, and exits with code 2 on missing held returns.
- `python scripts/run_research.py --endpoint-sensitivity`: also runs the conditional scenario and refreshes its report; exits with code 0 when that requested scenario completes.
- `python scripts/run_research.py --validate`: runs synthetic checks without course data.

Start with [README.md](README.md) for the files to review and share. Detailed data audits remain in `docs/`; raw inputs stay local.
"""
    report = re.sub(
        r"\]\(([^)]+)\)", lambda match: "](" + (docs_link(match.group(1))) + ")", report
    )
    (DOCS_DIR / "DATA_STATUS.md").write_text(report)
