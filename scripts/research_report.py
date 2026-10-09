"""Presentation formatting only; calculations live in research_statistics/backtest."""
from pathlib import Path
import hashlib
import json
import os
import re
os.environ.setdefault('MPLCONFIGDIR', '/tmp/qps-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
from src.backtest.research_statistics import CLASS_NAMES, risk_diagnostics
from src.config import DOCS_DIR, PROJECT_ROOT, QPS_OUTPUT_DIR, QPS_REPORT_DIR

ROOT = PROJECT_ROOT
OUT = QPS_OUTPUT_DIR / 'risk'
COLORS = ['#2676a5', '#ce7c27', '#358574', '#9563a5']


def save(fig, name, out):
    fig.savefig(out/f'{name}.png', dpi=150)
    plt.close(fig)


def style(axis, percent=False):
    axis.grid(alpha=.2)
    if percent:
        axis.yaxis.set_major_formatter(PercentFormatter(1))


def make_charts(classes, counts, autocorr, ledgers, settings, out=OUT):
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    conditional = 'Conditional March 1997 endpoint assumption' if out.name == 'endpoint_sensitivity' else ''
    dates = classes.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(11, 4), layout='constrained')
    ax.stackplot(dates, *[counts[c] for c in CLASS_NAMES], labels=list(CLASS_NAMES.values()), colors=COLORS, alpha=.85)
    ax.axhline(10, color='black', linestyle='--', label='Portfolio minimum: 10')
    ax.set(title='Prior-eligible instruments • January 1976–December 2014', ylabel='Instrument count')
    ax.legend(ncol=3, fontsize=9, loc='upper left'); style(ax)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, 'eligible_counts', out)

    fig, ax = plt.subplots(figsize=(11, 4.5), layout='constrained')
    for (group, s), color in zip(classes.items(), COLORS):
        # Missing class history is not filled with a zero return.
        cumulative = (1+s.loc[s.first_valid_index():]).cumprod(skipna=False)-1 if s.notna().any() else s
        ax.plot(cumulative.index.to_timestamp(), cumulative, label=CLASS_NAMES[group], color=color)
    ax.set(title='Equal-weight classes • compound from first eligible month, stop at any unknown return',
           ylabel='Cumulative return (unscaled, before costs)')
    ax.legend(ncol=2, fontsize=9); style(ax, True)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, 'class_cumulative', out)

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout='constrained', sharex=True, sharey=True)
    for ax, (group, name), color in zip(axes.flat, CLASS_NAMES.items(), COLORS):
        q = autocorr[autocorr.asset_class.eq(group)]
        ax.errorbar(q.lag, q.rho, yerr=np.vstack([q.rho-q.ci_low, q.ci_high-q.rho]), fmt='o-',
                    capsize=3, color=color, linewidth=1)
        ax.axhline(0, color='gray', linewidth=1)
        ax.set(title=f'{name} | matched n = {q.matched_months.min()}–{q.matched_months.max()}',
               xlabel='Monthly lag', ylabel='Spearman correlation', xticks=range(1, 13))
        style(ax)
    fig.suptitle((conditional+'\n' if conditional else '')+'Monthly class-return autocorrelation • approximate 95% HAC intervals\nExploratory: 48 comparisons; HAC bandwidth equals return lag', fontsize=12)
    save(fig, 'autocorrelation', out)

    if not ledgers:
        return

    names = [('Baseline trend', 'trend', COLORS[0]), ('Matching STATIC', 'static', COLORS[1])]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout='constrained')
    for label, strategy, color in names:
        ledger = ledgers[f'correlated_band10_5bps_{strategy}']
        wealth = ledger.nav_end
        axes[0].plot(dates, wealth-1, label=label, color=color)
        axes[1].plot(dates, wealth/wealth.cummax().clip(lower=1)-1, label=label, color=color)
    for ax, title in zip(axes, ['Compounded net returns', 'Drawdowns from prior peak']):
        ax.set_title(title); ax.legend(fontsize=9); style(ax, True)
    fig.suptitle((conditional+'\n' if conditional else '')+'1976–2014 • 5 bps trading costs • ±10% bands • zero interest')
    save(fig, 'performance', out)

    fig, axes = plt.subplots(3, 1, figsize=(11, 10), layout='constrained', sharex=True)
    for label, strategy, color in names:
        ledger = ledgers[f'correlated_band10_5bps_{strategy}']
        timeline, _ = risk_diagnostics(ledger)
        axes[0].plot(dates, timeline.realized_gross_vol_36m, label=f'{label}: realized gross', color=color)
        axes[0].plot(dates, timeline.forecast_rms_36m, label=f'{label}: forecast RMS', color=color, linestyle='--')
        axes[1].plot(dates, timeline.gross_after_cost, label=label, color=color)
        axes[2].plot(dates, timeline.drawdown, label=label, color=color)
    axes[0].set_title('36-month realized volatility and forecasts over the same window')
    axes[1].set_title('Gross exposure / capital after rebalance costs')
    axes[1].axhline(3, color='gray', linestyle='--', label='3× rebalance cap')
    axes[2].set_title('Net drawdowns')
    for i, ax in enumerate(axes):
        style(ax, i != 1); ax.legend(fontsize=8, ncol=2)
    if conditional:
        fig.suptitle(conditional, fontsize=11)
    save(fig, 'risk', out)


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---']+['---:']*(len(headers)-1)) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])



def validation_summary():
    record = json.loads((OUT/'validation.json').read_text())
    current = all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest for path, digest in record['files'].items())
    return f"{record['passed']} tests pass" if current else 'Validation record needs refreshing'


def write_report(metrics, alphas, class_stats, autocorr, attribution, audit, settings, base,
                 out=OUT, report_path=QPS_REPORT_DIR / 'REPORT.md', assumption=None, stability=None):
    """A concise report; calculation details and audit evidence remain linked appendices."""
    main = metrics[(metrics.band == .1) & (metrics.cost_bps == 5)].set_index('strategy')
    alpha = alphas[(alphas.band == .1) & (alphas.cost_bps == 5) & (alphas.hac_lags == 6)].iloc[0]
    trend = main.loc['trend']
    no_band = metrics[(metrics.band == 0) & (metrics.cost_bps == 5) & metrics.strategy.eq('trend')].iloc[0]
    coverage = [[r.name, r.instruments, f'{r.instrument_observations:,}', r.months, r.first_month]
                for r in class_stats.itertuples(index=False)]
    stats = [[r.name, f'{r.mean_monthly:.2%}', f'{r.std_monthly:.2%}', f'{r.mean_ann:.2%}',
              f'{r.vol_ann:.2%}', f'{r.sharpe:.2f}'] for r in class_stats.itertuples(index=False)]
    results = []
    for label, field, format_spec in [('Annual mean', 'mean_ann', '.2%'), ('CAGR', 'cagr', '.2%'),
                                      ('Annual volatility', 'vol_ann', '.2%'), ('Net Sharpe', 'sharpe', '.2f'),
                                      ('Maximum drawdown', 'max_drawdown', '.2%'),
                                      ('Annual turnover / capital', 'turnover_ann', '.2f'),
                                      ('Annual direct cost drag', 'mean_cost_ann', '.3%')]:
        results.append([label]+[format(main.loc[s, field], format_spec) for s in ['trend', 'static']])
    costs = [[r.strategy.upper(), f'{r.cost_bps:g}', f'{r.cagr:.2%}', f'{r.sharpe:.2f}']
             for r in metrics[metrics.band.eq(.1)].itertuples(index=False)]
    risk = [[s.upper(), f'{r.avg_gross_exposure:.2f}×', f'{r.rms_forecast_vol:.2%}', f'{r.realized_predicted_ratio:.2f}']
            for s, r in main.iterrows()]
    classes = [[CLASS_NAMES[r.asset_class], f'{r.net_mean_ann:.2%}', f'{r.contribution_vol_ann:.2%}',
                f'{r.avg_gross_exposure:.2f}×', f'{r.avg_forecast_vol_contribution:.2%}']
               for r in attribution['trend'].itertuples(index=False)]
    uncertainty = []
    for group, name in CLASS_NAMES.items():
        q = autocorr[autocorr.asset_class.eq(group)]
        uncertainty.append([name, f'{q.matched_months.min()}–{q.matched_months.max()}',
                            f'{int(q.p_approx.lt(.05).sum())}/12'])
    assumption_note = ('**All results are conditional on an unverified endpoint assumption:** March 27, 1997 is used as '
                       'the March endpoint for DT, GS, LX and SS, restoring eight March/April returns. '
                       '[Exact changes](output/endpoint_sensitivity/endpoint_changes.csv) · '
                       '[Evidence note](../../docs/ENDPOINT_DECISION.md) · [Preserved-policy status](../../docs/DATA_STATUS.md).'
                       if assumption is not None else '')
    stability_text = ''
    if stability is not None:
        periods = stability[stability.period.isin(['1976–1984', '1985–1994', '1995–2004', '2005–2014'])]
        block_rows = []
        for period in periods.period.drop_duplicates():
            pair = periods[periods.period.eq(period)].set_index('strategy')
            block_rows.append([period, f'{pair.loc["trend", "mean_ann"]:.2%}', f'{pair.loc["static", "mean_ann"]:.2%}',
                               f'{pair.loc["trend", "sharpe"]:.2f}', f'{pair.loc["static", "sharpe"]:.2f}'])
        stability_text = '\n'+table(['Period', 'Trend mean', 'STATIC mean', 'Trend Sharpe', 'STATIC Sharpe'], block_rows)
        stability_text += '\n\nThese are descriptive blocks of the existing trading path, not new holdouts. Recent mean returns are weaker; the full-period advantage is not uniform. [Block and crisis diagnostics](output/risk/stability.csv).\n'
    report = f'''# Managed futures: 15-minute midterm report

{assumption_note}

| Section | Time | Show | Point to make |
| :--- | ---: | :--- | :--- |
| Question and answer | 1 min | Opening takeaway | Does trend direction add value under the same controls? |
| Data | 1.5 min | Coverage chart | 1976–2014; January is flat; results use one explicit endpoint assumption |
| Asset classes | 2 min | Statistics and cumulative chart | Equal-weight prior-eligible class portfolios; unequal histories matter |
| Autocorrelation | 1.5 min | Rank-correlation chart | Persistence evidence is limited and exploratory |
| Construction | 2 min | Four-step strategy description | Direction, risk sizing, limits, then bands; explain STATIC |
| Results | 3 min | Main comparison and drawdowns | Full-period improvement; recent performance is more modest; costs matter |
| Risk | 2.5 min | Rolling risk and class attribution | Forecasts underpredict fluctuations; commodities dominate average forecast risk |
| Limits and improvements | 1.5 min | Three priorities | Verify data/execution, improve risk calibration, then test unexamined history |

## 1. Question and answer — 1 min

**Question:** does following 12-month trends add value over an always-long portfolio under the same controls?

**Answer:** trend improves full-period risk-adjusted performance versus matching STATIC in this conditional historical study. Recent performance is more modest. The result supports further research; data provenance, execution and risk calibration still need work.

## 2. Data — 1.5 min

| Item | Definition |
|---|---|
| Evaluation | January 1976–December 2014; 468 monthly observations |
| Inputs | Monthly returns, daily futures prices and an instrument/class map |
| Universe | 58 retained columns; YM duplicate and EC unresolved identity excluded |
| Timing | Prior 12-month signal and 36-month risk windows; earlier data initialize the model |
| Source selection | RL/ER is one exposure; switch to ER in {audit['source_switch_month']} using history known through t−2 |

January 1976 has {audit['eligible_at_start']} eligible instruments, below the minimum of {audit['minimum_required']}; that month is flat. Trading starts in {audit['first_investable_month']}. Missing held returns fail explicitly. The original eight calendar-supported return corrections are retained.

![Eligible instruments](output/risk/eligible_counts.png)

**Point to make:** the requested dates are retained, including the flat January month. All displayed results use the explicit endpoint assumption stated above.

## 3. Asset classes — 2 min

Each class return equally weights instruments eligible before the month. Statistics are calculated from the class portfolio series. Empty classes remain missing; an unavailable eligible constituent makes the whole class return missing.

{table(['Class', 'Instruments', 'Eligible instrument-months', 'Portfolio months', 'First month'], coverage)}

{table(['Class', 'Monthly mean', 'Monthly SD', 'Annual mean', 'Annual vol', 'Sharpe'], stats)}

Annual mean = 12 × monthly mean; annual volatility = √12 × sample monthly SD; Sharpe assumes **RF = 0**. Coverage differs across classes, so these available-history estimates are not a fully matched four-class comparison. Compounding starts at each class's first eligible month and stops at an unknown subsequent return.

![Compounded class returns](output/risk/class_cumulative.png)

**Takeaway:** fixed income has the highest descriptive Sharpe, followed by equities; currencies are weakest. Differing history and eligibility prevent a direct replication of the lecture's class statistics.

## 4. Autocorrelation — 1.5 min

Spearman rank correlation compares each **class portfolio's monthly return** with its calendar-shifted return at lags 1–12. Missing pairs are removed after shifting. This differs from averaging instrument autocorrelations.

![Class autocorrelation](output/risk/autocorrelation.png)

{table(['Class', 'Matched pairs across lags', 'Approximate p < 0.05'], uncertainty)}

Approximate 95% intervals use standardized-rank regressions with calendar-spaced Bartlett HAC scores, bandwidth equal to return lag, n/(n−2) correction and t(n−2) critical values. All 48 comparisons are exploratory and unadjusted for multiple testing.

**Takeaway:** the class diagnostics provide limited persistence evidence. They do not establish the profitability or optimality of the 12-month signal. [All estimates and intervals](output/risk/autocorrelation.csv).

## 5. Construction — 2 min

1. **Direction:** sign of the sum of the previous 12 monthly returns; zero means flat.
2. **Risk:** previous 36 months; 2% annual instrument-volatility floor; correlations shrunk 50% toward zero.
3. **Size:** initial magnitude 0.40 / (eligible count × annual instrument volatility); reduce proportionally to a **10% forecast-risk ceiling** and **3× gross cap** after rebalance costs.
4. **Trade:** use a ±10% relative band; entries, exits and reversals execute immediately. Hard limits override bands.

STATIC is always long with identical eligibility, risk estimates, limits, bands and costs; its own forecast determines scaling. The comparison measures the value of trend direction under matching controls.

**Difference from Lecture 6:** the lecture baseline uses expanding volatility with zero cross-instrument covariance; its later extension targets 11% forecast volatility. Our model uses a fixed 36-month window, shrinkage, a 10% ceiling, gross cap and bands. It scales down but does not scale up to a risk target. This is an enhanced baseline, not a matched lecture replication.

## 6. Results — 3 min

Net returns; **5 bps per unit of traded exposure**, ±10% bands, RF = 0. Annual mean is arithmetic; CAGR compounds monthly returns.

{table(['Metric', 'Trend', 'STATIC'], results)}

Trend/STATIC correlation is **{alpha.correlation:.2f}**. Annualized alpha is **{alpha.alpha_ann:.2%}**, with 95% HAC interval **[{alpha.alpha_ci_low_ann:.2%}, {alpha.alpha_ci_high_ann:.2%}]**. Alpha is 12 × the monthly regression intercept against STATIC, using 6 HAC lags; its interval excludes strategy-selection and data-provenance uncertainty.

![Net returns and drawdowns](output/risk/performance.png)

**Takeaway:** trend has higher full-period CAGR and Sharpe, with a much smaller drawdown. The evidence is conditional and in sample.
{stability_text}
### Implementation costs

{table(['Portfolio', 'Cost (bps)', 'CAGR', 'Sharpe'], costs)}

Costs cover initial entry, actual drift-adjusted trades, RL/ER close/open trades and final liquidation. They are illustrative; historical spread, impact and roll costs are unavailable.

The ±10% band reduces trend turnover by **{1-trend.turnover_ann/no_band.turnover_ann:.1%}** and direct annual cost drag by **{(no_band.mean_cost_ann-trend.mean_cost_ann)*10000:.2f} bps** versus no band. Net annual mean changes by **{(trend.mean_ann-no_band.mean_ann)*10000:+.2f} bps**. The band saves trading but does not improve every performance measure. [All cost and no-band comparisons](output/risk/comparison.csv).

## 7. Risk — 2.5 min

{table(['Portfolio', 'Average gross exposure', 'RMS forecast vol', 'Calibration SD'], risk)}

Calibration SD measures gross return variability after dividing each return by its preceding forecast monthly volatility; one is ideal. The values above show underprediction. A 10% forecast ceiling is not a realized-volatility or loss guarantee.

![Risk through time](output/risk/risk.png)

The risk plot compares trailing 36-month realized gross volatility with RMS forecasts for **the same 36 months**. Exposure limits apply at rebalances; exposure can drift between them.

Trend class attribution:

{table(['Class', 'Annual net contribution', 'Contribution vol', 'Average gross exposure', 'Average forecast-vol contribution'], classes)}

Monthly net class contributions include actual instrument costs and sum to net portfolio return. Annual means and signed Euler forecast-risk contributions add; **class volatilities do not**. Classes have unequal risk allocations, with commodities contributing most of the average forecast risk. [Full attribution](output/risk/trend_class_attribution.csv).

## 8. Limits and improvements — 1.5 min

**Suitable for a midterm:** a clear economic idea, a fair STATIC comparison, transparent costs, and reproducible accounting. **Evidence for future performance is limited:** the sample has been studied repeatedly, the endpoint assumption remains unverified, and execution/roll/FX conventions are idealized. No fresh out-of-sample test or superiority over the lecture is established.

Three priorities:

1. **Verify data and execution:** resolve venue/vendor endpoints and validate next-session fills, roll/FX conventions and contract accounting.
2. **Improve risk calibration:** test a more responsive estimator; evaluate true volatility targeting and deliberate class-risk budgets as future extensions.
3. **Test unexamined history:** freeze the rules, evaluate them on new data, then monitor forward paper trading.

These improvements are proposed future work.

**Validation:** {validation_summary()}; the preserved 2000–2014 refactor replay matches all 12 archived runs. [Code guide](../../docs/CODE_GUIDE.md) · [Methods](../../docs/RISK_METHODS.md) · [Validation](../../docs/VALIDATION.md) · [15-minute presentation guide](../../docs/MIDTERM_GUIDE.md).

Reproduce: `python scripts/run_research.py --endpoint-sensitivity`. The standalone HTML embeds all five figures.
'''
    report = report.replace('output/risk/', str(out.relative_to(QPS_REPORT_DIR))+'/')
    report_path.write_text(report)
    if assumption is not None:
        # Keep the earlier filename as a compatible copy of the main presentation.
        (QPS_REPORT_DIR / 'ENDPOINT_SENSITIVITY.md').write_text(report)


def docs_link(link):
    """Re-point a report-relative link so it resolves from docs/."""
    if link.startswith(('https://', 'http://', '#')):
        return link
    if link.startswith('../../docs/'):
        return link[len('../../docs/'):]
    if link.startswith(('output/', 'ENDPOINT_SENSITIVITY')):
        return '../' + str(QPS_REPORT_DIR.relative_to(PROJECT_ROOT)) + '/' + link
    return '../' + link


def write_blocked_report(class_stats, autocorr, audit, failures):
    rows = [[f['strategy'].upper(), f['error']] for f in failures]
    report = f'''# Preserved data policy: status and endpoint issue

**The 1976–2014 comparison stops on missing held returns.** The simulator preserves the existing endpoint rules and fails explicitly; full-period portfolio metrics are unavailable under this policy.

For the completed, clearly labeled conditional research, read [ENDPOINT_SENSITIVITY.md](ENDPOINT_SENSITIVITY.md) or [offline HTML](ENDPOINT_SENSITIVITY.html). That report uses March 27 as an unverified March 1997 endpoint for four instruments.

## What blocks evaluation

{table(['Portfolio', 'Simulator failure'], rows)}

DT, GS and LX are held in March 1997. Their last March observation is March 27, four calendar days before the March 31 target. The preserved three-day freshness rule rejects it, leaving March and April returns missing. SS has the same gap but is ineligible then. Historical venue closure and vendor identity remain unverified.

The [candidate return table](output/risk/proposed_endpoint_returns.csv) contains the eight implied March/April returns. They are not applied to primary inputs. The separate sensitivity uses exact observed closes in a copy of the return matrix, then recomputes the full trading path. [Evidence and decision note](../../docs/ENDPOINT_DECISION.md).

## Sample and validation

The requested 468 months remain January 1976–December 2014. January 1976 has {audit['eligible_at_start']} eligible instruments versus the required {audit['minimum_required']}, so it is flat. First trading month: {audit['first_investable_month']}.

{validation_summary()}. The archived 2000–2014 refactor replay is independent of the endpoint sensitivity. [Validation record](output/risk/validation.json) · [Sample audit](output/risk/sample_audit.json) · [Run status](output/risk/run_status.json).

## Reproduce

- `python scripts/run_research.py`: preserves the data policy, refreshes this status report, and exits with code 2 on missing held returns.
- `python scripts/run_research.py --endpoint-sensitivity`: also runs the conditional scenario and refreshes its report; exits with code 0 when that requested scenario completes.
- `python scripts/run_research.py --validate`: runs synthetic checks without course data.

Start with [README.md](README.md) for the files to review and share. Detailed data audits remain in `docs/`; raw inputs stay local.
'''
    report = re.sub(r'\]\(([^)]+)\)', lambda match: ']('+(docs_link(match.group(1)))+')', report)
    (DOCS_DIR / 'DATA_STATUS.md').write_text(report)
