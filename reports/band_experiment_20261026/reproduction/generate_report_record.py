import json,os
from pathlib import Path
import numpy as np
import pandas as pd
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/qps-step3-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path('/Users/anaybhat/Documents/managed_futures'); report=root/'reports/band_experiment_20261026'; out=report/'output'
metrics=pd.read_csv(out/'comparison.csv'); pairs=pd.read_csv(out/'paired_comparison.csv'); ci=pd.read_csv(out/'paired_intervals.csv'); periods=pd.read_csv(out/'subperiods.csv'); trades=pd.read_csv(out/'turnover_breakdown.csv')
joined=pairs.merge(ci.query('block_months == 12'),on='run')
trend=metrics.query('strategy == "trend" and cost_bps == 2').set_index('band')

def table(headers,rows):
 return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])

def metric_rows(strategy):
 rows=[]
 for band in [0,.05,.1]:
  t=metrics.query('strategy == @strategy and band == @band').set_index('cost_bps')
  rows.append([f'{band:.0%}',f'{t.loc[1,"cagr"]:.2%}',f'{t.loc[2,"cagr"]:.2%}',f'{t.loc[2,"sharpe"]:.3f}',f'{t.loc[2,"vol_ann"]:.2%}',f'{t.loc[2,"max_drawdown"]:.2%}',f'{t.loc[2,"turnover_ann"]:.2f}×'])
 return rows

paired_rows=[]
for row in joined.query('strategy == "trend"').itertuples():
 paired_rows.append([f'{row.band:.0%}',row.cost_bps,f'{row.net_difference_ann*10000:+.2f}',f'[{row.ci_low*10000:+.2f}, {row.ci_high*10000:+.2f}]',f'[{row.family_ci_low*10000:+.2f}, {row.family_ci_high*10000:+.2f}]'])
block_rows=[]
for band in [0,.05]:
 for row in periods.query('strategy == "trend" and band == @band and cost_bps == 2').itertuples():
  block_rows.append([f'{band:.0%}',row.period,f'{row.mean_difference_ann*10000:+.2f}'])
trade_rows=[]
for category in ['resizes','reversals','entries','exits','source_switches','terminal_liquidation']:
 t=trades.query('strategy == "trend" and cost_bps == 2 and category == @category').set_index('band')
 trade_rows.append([category.replace('_',' ').title()]+[f'{t.loc[b,"turnover_ann"]:.3f}' for b in [0,.05,.1]])
risk_rows=[]
for band,r in trend.iterrows():
 risk_rows.append([f'{band:.0%}',f'{r.avg_gross_exposure:.3f}×',f'{r.realized_predicted_ratio:.3f}',f'{r.mean_target_distance_l1:.3f}×',f'{r.mean_raw_target_distance_l1:.3f}×'])
fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
rows=joined.query('strategy == "trend"').reset_index(drop=True)
y=np.arange(len(rows))
axes[0].errorbar(rows.net_difference_ann*10000,y,xerr=np.vstack([(rows.net_difference_ann-rows.ci_low)*10000,(rows.ci_high-rows.net_difference_ann)*10000]),fmt='o',capsize=4,color='#2676a5')
axes[0].axvline(0,color='gray',ls='--');axes[0].set_yticks(y,[f'{r.band:.0%} band · {r.cost_bps:g} bps' for r in rows.itertuples()]);axes[0].set(xlabel='Annual mean improvement vs 10% band (bps of NAV)',title='Paired mean difference and nominal 95% interval');axes[0].invert_yaxis();axes[0].grid(axis='x',alpha=.2)
wide=trades.query('strategy == "trend" and cost_bps == 2').pivot(index='band',columns='category',values='turnover_ann').reindex([0,.05,.1])
bottom=np.zeros(3)
for category in ['reversals','resizes','entries','exits','source_switches','terminal_liquidation']:
 axes[1].bar(np.arange(3),wide[category],bottom=bottom,label=category.replace('_',' ').title());bottom+=wide[category].to_numpy()
axes[1].set_xticks(np.arange(3),['0%','5%','10%']);axes[1].set(xlabel='Relative band',ylabel='Annual one-way turnover / NAV',title='Most turnover comes from reversals · 2 bps');axes[1].legend(fontsize=8,ncol=2);axes[1].grid(axis='y',alpha=.2)
fig.suptitle('V2 TREND · conditional 1976–2014 history\n20,000 paired circular-block bootstrap draws; 12-month blocks',fontsize=12)
fig.savefig(report/'band_comparison.png',dpi=150);plt.close(fig)

text=f'''# Step 3: trading-band experiment

**Decision: retain the 10% relative trading band at the 2 bps primary cost.** The 0% and 5% alternatives offer small gains in historical mean return and CAGR, but neither meets the frozen evidence screen. Their paired uncertainty intervals include zero; both have lower Sharpe and deeper drawdowns. This does not prove the true return advantage is zero.

All 12 planned runs completed: v2 TREND and matching STATIC × 0/5/10% bands × 1/2 bps. Signals, covariance estimates, dates, execution timing and cost convention are fixed. Results remain **conditional on the unverified March 1997 endpoint assumption** and use already-inspected 1976–2014 history. No roll-cost work or new signal experiment has started.

## Main results

**V2 TREND**

{table(['Band','CAGR at 1 bps','CAGR at 2 bps','Sharpe at 2 bps','Volatility at 2 bps','Drawdown at 2 bps','Turnover at 2 bps'],metric_rows('trend'))}

**Matching STATIC**

{table(['Band','CAGR at 1 bps','CAGR at 2 bps','Sharpe at 2 bps','Volatility at 2 bps','Drawdown at 2 bps','Turnover at 2 bps'],metric_rows('static'))}

The 10% band has the highest Sharpe and shallowest drawdown of the three bands for both portfolios at both cost assumptions. TREND gives up a small amount of historical compounded growth in exchange for lower fluctuations. STATIC also has higher CAGR with the 10% band.

![Band comparison and turnover decomposition](band_comparison.png)

## Gross performance versus costs saved

At 2 bps, moving TREND from no band to the 10% band cuts annual turnover from {trend.loc[0,'turnover_ann']:.3f}× to {trend.loc[.1,'turnover_ann']:.3f}× NAV, a reduction of {(1-trend.loc[.1,'turnover_ann']/trend.loc[0,'turnover_ann']):.1%}. Annual direct costs fall from {trend.loc[0,'mean_cost_ann']:.3%} to {trend.loc[.1,'mean_cost_ann']:.3%}, saving {(trend.loc[0,'mean_cost_ann']-trend.loc[.1,'mean_cost_ann'])*10000:.2f} bps of NAV per year.

The same change reduces annual gross arithmetic mean by {(trend.loc[0,'gross_mean_ann']-trend.loc[.1,'gross_mean_ann'])*10000:.2f} bps, leaving annual net mean {(trend.loc[0,'mean_ann']-trend.loc[.1,'mean_ann'])*10000:.2f} bps lower. **The band does not pay for itself through transaction-cost savings alone in this sample.** Retention rests on uncertainty about the small return gain and the observed risk tradeoff, not a claim that minimizing turnover maximizes returns. Each path was fully resimulated; these figures include fee feedback into NAV and holdings.

[Exact gross/cost/net decomposition for all candidates](output/paired_comparison.csv).

## Paired uncertainty and the decision screen

The comparison is candidate minus 10% band, using identical monthly dates and cost rates. Values below are **annual arithmetic-mean differences in bps of NAV**, not CAGR differences.

{table(['Candidate band','Cost (bps)','Mean gain','Nominal 95% interval','Family-adjusted interval'],paired_rows)}

The frozen screen requires at least 10 bps of annual mean improvement at both cost rates, positive family-adjusted lower bounds for all three bootstrap block lengths, and improvement in at least three of four historical blocks. Drawdown, calibration and tracking are then reviewed before adoption. The 10 bps threshold is a declared research convention, not an estimated optimum.

The calculation uses 20,000 circular moving-block draws, resampling the **paired difference vectors together**. The primary block length is 12 months; 6 and 24 months are sensitivity checks. Nominal intervals use percentile bounds. Bonferroni bounds use 0.3125% and 99.6875% quantiles for eight comparisons (two candidate bands × two costs × two portfolios), providing approximate 95% family coverage for each block length. They do not account for the entire earlier strategy search or remove nonstationarity and data-provenance uncertainty. No block length was selected for its most favorable result.

The no-band candidate meets the mean-gain threshold and improves mean return in all four blocks, but fails the uncertainty requirement. The 5% band also fails the mean-gain threshold; it improves three of four blocks. Both fail the adjusted-interval requirement. **No candidate is promoted.** [All intervals](output/paired_intervals.csv) · [Frozen specification](output/trial_specification.json) · [Screen results](output/candidate_screen.json).

## Stability across historical blocks

TREND annual mean gain versus the 10% band, at 2 bps:

{table(['Candidate','Historical block','Gain (bps/year)'],block_rows)}

Both costs give the same positive-block counts. These windows describe the existing trading paths; they are not fresh holdouts or independently optimized/restarted portfolios. [All subperiod return, risk and drawdown metrics](output/subperiods.csv).

## What the band changes

Annual TREND turnover by trade type, at 2 bps (units of NAV per year):

{table(['Trade type','0% band','5% band','10% band'],trade_rows)}

The main reduction comes from **resizing existing same-direction positions**. Source switches include the full close/open legs and take precedence over the other categories; they are not added again to reversal turnover. Resizes include any reductions imposed by hard risk limits. Entry, reversal and liquidation quantities can differ slightly because carried holdings and portfolio scaling differ.

All **1,648 instrument-level target sign reversals** execute in the correct direction in the same month under every band and cost case. Bands do not postpone those direction changes. Their sizes can still differ because hard portfolio limits override targets. [Execution checks](output/reversal_execution.csv).

The descriptive before/during/after reversal-month comparison is in [reversal diagnostics](output/reversal_diagnostics.csv). There is at least one instrument reversal in 438 of 468 months, so these overlapping portfolio-level windows are not an isolated-event study and offer little independent evidence about rare turning points. They are not used as a selection criterion.

## Risk and target tracking

TREND at 2 bps:

{table(['Band','Average gross exposure','Risk calibration','Mean distance to bounded target','Mean distance to raw target'],risk_rows)}

Target distance is the sum of absolute exposure differences, averaged over months, in units of beginning-month NAV. The bounded target applies the existing gross/risk limits before bands; the raw target is the inverse-volatility signal position before those portfolio limits. Even the zero-band run can differ slightly from its bounded target because fees require further reductions. Wider bands allow more tracking deviation. The calibration shortfall remains under every band; a band change does not solve it.

## Validation and reproducibility

- **143 tests pass**, including trade decomposition with drift, reversal, source close/open and final liquidation, plus paired-bootstrap checks.
- All 12 simulations cover 468 months and reconcile costs, gross/net P&L and turnover categories. No rebalance gross/risk-limit breaches occur. The eight shared 0/10% runs reproduce Step 2 within numerical tolerance. [Validation](output/validation.json).
- Verified all Step 2 artifact hashes and all 65 raw-input hashes before execution. The experiment uses the frozen Step 2 conditional return panel, source schedule and known-at dates. It does not substitute a new data scenario or claim a new raw reconstruction.
- The production risk config, raw files and prior result packages remain unchanged. [Reproduction guide](REPRODUCE.md) · [Trial/source manifest](provenance.json).

**Stop after Step 3.** Step 4 is the contract/roll-data audit and separate roll-cost accounting, subject to the data gate. It has not started.
'''
(report/'SUMMARY.md').write_text(text)
(report/'decision.json').write_text(json.dumps(dict(primary_band=.1,primary_cost_bps=2,adopted_change=False,reason='Neither candidate satisfies the frozen uncertainty screen; narrower bands have lower Sharpe and worse drawdown despite small historical return gains.',step_3_complete=True,step_4_started=False),indent=2)+'\n')
print('Step 3 report and chart written.')
