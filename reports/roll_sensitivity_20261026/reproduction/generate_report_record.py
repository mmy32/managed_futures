import json,os
from pathlib import Path
import numpy as np,pandas as pd
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/qps-step4-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
root=Path('/Users/anaybhat/Documents/managed_futures'); dest=root/'reports/roll_sensitivity_20261026'; out=dest/'output'
t=pd.read_csv(out/'comparison.csv')
trend=t.query('strategy == "trend" and trade_bps == 2').set_index(['calendar','roll_bps'])
trend1=t.query('strategy == "trend" and trade_bps == 1').set_index(['calendar','roll_bps'])
static=t.query('strategy == "static" and trade_bps == 2').set_index(['calendar','roll_bps'])
keys=[('trade_only',0)]+[(c,r) for c in ['quarterly_jan','quarterly_feb','quarterly_mar','monthly'] for r in [1,2]]
labels={'trade_only':'Trade only','quarterly_jan':'Jan/Apr/Jul/Oct','quarterly_feb':'Feb/May/Aug/Nov','quarterly_mar':'Mar/Jun/Sep/Dec','monthly':'Every month'}
rows=[]
for key in keys:
 a,b=trend1.loc[key],trend.loc[key]
 rows.append([labels[key[0]],key[1],f'{a.cagr:.2%}',f'{b.cagr:.2%}',f'{b.roll_cost_ann*10000:.2f}',f'{b.sharpe:.3f}'])
def table(headers,rows):
 return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])
selected=[('trade_only',0),('quarterly_mar',1),('quarterly_mar',2),('monthly',1),('monthly',2)]
chart=trend.loc[selected]
x=np.arange(len(chart));names=['Trade only','Quarterly\n1 bp/roll','Quarterly\n2 bps/roll','Monthly\n1 bp/roll','Monthly\n2 bps/roll']
fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
axes[0].bar(x,chart.ordinary_cost_ann*10000,label='Ordinary trades',color='#2676a5')
axes[0].bar(x,chart.roll_cost_ann*10000,bottom=chart.ordinary_cost_ann*10000,label='Assumed roll execution',color='#ce7c27')
axes[0].set(ylabel='Annual booked cost (bps of NAV)',title='Roll frequency can materially change costs');axes[0].legend(fontsize=9)
axes[1].bar(x,chart.cagr,color='#2676a5');axes[1].yaxis.set_major_formatter(PercentFormatter(1));axes[1].set(ylabel='Net CAGR',title='Conditional historical growth',ylim=(0,.13))
for i,r in enumerate(chart.itertuples()):axes[1].text(i,r.cagr+.002,f'{r.cagr:.2%}',ha='center',fontsize=9)
for ax in axes:ax.set_xticks(x,names);ax.grid(axis='y',alpha=.2)
fig.suptitle('Hypothetical roll sensitivity · V2 TREND · regular trades 2 bps · band 10%\nQuarterly illustration: Mar/Jun/Sep/Dec; roll quotes cover the complete close/open',fontsize=11)
fig.savefig(dest/'roll_sensitivity.png',dpi=150);plt.close(fig)
monthly=trend.loc[('monthly',2)];base=trend.loc[('trade_only',0)]
text=f'''# Step 4: roll-cost audit and conditional sensitivity

**Step 4 is complete as an assumption-based sensitivity. A verified historical roll model is not yet supportable.** The available files have no dated contract chain or roll schedule. The production reference remains the 2 bps trade-only case with a 10% band; no empirical roll rate or calendar is adopted.

All 36 cases were fully resimulated. With regular trading at 2 bps, v2 TREND CAGR is **{base.cagr:.2%} trade-only**, about **11.21–11.30%** under quarterly roll assumptions, and **10.85–11.12%** under monthly assumptions. These figures are hypothetical additional execution charges on already-inspected history, still conditional on the March 1997 endpoint assumption.

## What the data establish

- All **62 daily files** contain only a date index, OHLC, volume and open interest. The asset map supplies underlying IDs, names, currencies and asset classes.
- The workbook contains benchmark/factor returns, not contracts or expiry metadata. There are no raw-data sidecars with contract specifications.
- Missing: dated delivery-contract identities, expiry and actual roll dates, multipliers/quote units, currency-conversion conventions and the vendor's adjustment lineage. Underlying IDs are not delivery-contract IDs.
- [Repository endpoint notes](../../docs/ENDPOINT_REVIEW.md) identify the inputs as already rolled, with the adjustment method unspecified. Neither price jumps nor volume patterns were treated as verified roll dates.

[Per-series audit](output/contract_data_audit.csv) · [Data-gate findings](output/data_gate.json).

## Rate and execution conventions

Ordinary trades retain the agreed **1 or 2 bps per unit of one-way traded notional / beginning-month NAV**. The additional roll quote is provisionally **1 or 2 bps per unit of continuing notional for the complete close/open**, equivalent to **0.5 or 1 bp per leg**. The lecture does not settle that basis; it must be confirmed before empirical use. The implementation also accepts explicitly labeled per-leg quotes and converts them to the complete-event basis.

At a scheduled beginning-of-month roll, matched continuing notional is:

`min(abs(drifted previous exposure), abs(executed exposure))`

Only same-direction positions qualify. The ordinary trade charge covers net resizing. For example, increasing a position from 0.50 to 0.75 NAV charges an ordinary 0.25 resize plus a roll of the 0.50 continuing exposure; it does not charge a full roll of 0.75 again. The journal contains the hypothetical close/open legs explicitly.

Entries, exits and full reversals already involve the needed trading legs and receive no extra scheduled-roll fee. A source switch supersedes a coincident assumed roll because the existing model already charges its full close/open. This is a **netted beginning-period execution assumption**, not proof that distinct real-world intramonth events coincide. Exact contract/event identities would be needed to distinguish separate events.

Roll charges enter the limit solver **before** positions are finalized. NAV, carried holdings, cash income and class attribution use the same total ordinary-plus-roll fee. Terminal liquidation remains a separate ordinary exit at the end of the final month. Total turnover includes both roll legs; total cost cannot be inferred by multiplying that turnover by the ordinary rate because the component rate bases differ.

Economic carry, calendar-spread P&L and continuous-price adjustments are not added as execution fees. Execution-cost coverage in the supplied series remains unverified, so these are conditional incremental scenarios rather than verified all-in investor returns.

## Fixed scenario grid and results

The experiment uses v2 TREND and matching STATIC, the existing signal/risk rules and 10% band, regular rates 1/2 bps, and roll quotes 1/2 bps. It includes three quarterly phases and a monthly calendar, each applied uniformly to all markets. The schedules are fixed assumptions known before the simulated sample, not observed contract histories. All three quarterly phases are reported; none was selected for favorable performance.

There are **32 roll scenarios plus four trade-only controls**, each covering the same 468 months. Complete specification: [assumptions](output/assumptions.json).

**V2 TREND:** roll quote is bps per completed roll; added drag is bps of NAV per year.

{table(['Assumed roll months','Roll quote','CAGR: ordinary 1 bp','CAGR: ordinary 2 bps','Added roll drag: ordinary 2 bps','Sharpe: ordinary 2 bps'],rows)}

These CAGRs come from resimulated trading paths, not subtraction of a fixed drag from the previous CAGR. Annual direct drag is 12 × mean monthly booked fees. The 1–2 bps roll assumptions are illustrative coefficients, not calibrated estimates or upper/lower bounds on actual costs.

![Roll cost and return sensitivity](roll_sensitivity.png)

In the monthly 2 bps complete-roll scenario, TREND rolls {monthly.rolled_notional_ann:.2f}× NAV per year of matched continuing exposure. That produces {monthly.roll_cost_ann*10000:.2f} bps of annual roll drag, in addition to {monthly.ordinary_cost_ann*10000:.2f} bps from ordinary trading. Compared with the trade-only case, CAGR falls by {(base.cagr-monthly.cagr)*10000:.2f} bps per year. Higher turnover from these hypothetical close/open events is recorded separately from ordinary portfolio rebalancing.

Matching STATIC falls from {static.loc[('trade_only',0),'cagr']:.2%} trade-only CAGR to {static.loc[('monthly',1),'cagr']:.2%}/{static.loc[('monthly',2),'cagr']:.2%} with monthly 1/2 bps roll quotes. Its low rebalancing turnover does not eliminate the need to maintain futures exposure through expiry. These remain scenario results, not verified implementation costs.

[All 36 cases, including risk and both cost components](output/comparison.csv) · [Class gross/ordinary-cost/roll-cost/net contributions](output/class_comparison.csv).

## Validation and preserved defaults

- **167 tests pass**, including unchanged holdings, flat positions, entry/exit/reversal overlap, coincident source switches, resize/roll decomposition, per-leg conversion, after-fee limits, terminal liquidation, cash income and future-schedule mutation.
- All 36 event journals reconcile to total notional and costs. Instrument/class gross returns less ordinary and roll fees reconcile to net returns; limits use total entry fees. Trade-only controls reproduce the four Step 2 references within numerical tolerance. [Run validation](output/validation.json).
- The engine's default has no roll schedule. Production cost/band settings and all raw input bytes are unchanged. Earlier reports and experiment packages are preserved.
- Compressed `*_events.csv.gz` journals list month, market, timing, event, signed exposure, one-way notional, fee and component. They represent NAV-normalized proxy events, not verified contract counts or fills. Executed exposures and per-run class attribution are retained alongside the ledgers.

## Cleanup and next step

Task-generated scratch work, duplicate temporary logs/scripts, Finder metadata and disposable caches were removed. Original Downloads files, immutable raw data and durable research/reproduction packages are retained. [Cleanup inventory](cleanup.json) · [Reproduction instructions](REPRODUCE.md) · [Source and input provenance](provenance.json).

**Stop after Step 4.** Step 5 is the liquidity/funding data inventory and feasibility assessment. It has not started. Actual roll-cost adoption also remains gated on dated contract metadata and adjustment/execution-cost lineage.
'''
(dest/'SUMMARY.md').write_text(text)
(dest/'decision.json').write_text(json.dumps(dict(step_4_complete=True,implementation='assumption_based_roll_sensitivity',actual_roll_history_supported=False,production_roll_model_adopted=False,primary_trade_bps=2,primary_band=.1,step_5_started=False),indent=2)+'\n')
print('Roll sensitivity report and figure created.')
