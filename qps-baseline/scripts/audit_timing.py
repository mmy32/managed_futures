"""Timing audit and descriptive stability checks; these are not OOS validation."""
from pathlib import Path
import copy,json,hashlib
import numpy as np
import pandas as pd
from strategy_inputs import load_strategy_inputs
from risk_model import build_forecasts,BandPolicy
from backtest import simulate,performance,regression_alpha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/timing_audit'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    settings=json.loads((ROOT/'config/risk_config.json').read_text())
    base=json.loads((ROOT/settings['base_config']).read_text())
    returns,source,known,schedule=load_strategy_inputs(settings,write=True)
    sample=returns.loc[base['start']:base['end']]
    meta=pd.read_csv(ROOT/'data/AssetMapCsv.csv').set_index('ID')
    rows=[];series={};alphas=[]
    for lag in [1,2]:
        cfg=copy.deepcopy(base);cfg['information_lag_months']=lag
        target,cov,diag=build_forecasts(returns,meta,cfg,settings,'correlated')
        pair={}
        for name in ['trend','static']:
            ledger,_=simulate(sample,target[name],5,source.loc[sample.index],
                              position_policy=BandPolicy(cov,settings,.1),source_known_at=known.loc[sample.index])
            ledger.to_csv(OUT/f'lag{lag}_{name}_ledger.csv')
            rows.append(dict(information_lag_months=lag,strategy=name,**performance(ledger)))
            series[f'lag{lag}_{name}']=ledger.net_return
            pair[name]=ledger.net_return
        a,_=regression_alpha(pair['trend'],pair['static'].to_frame('STATIC'),6)
        alphas.append(dict(information_lag_months=lag,**a))
    metrics=pd.DataFrame(rows);metrics.to_csv(OUT/'timing_comparison.csv',index=False)
    pd.DataFrame(alphas).to_csv(OUT/'timing_alpha.csv',index=False)
    pd.DataFrame(series).to_csv(OUT/'monthly_returns.csv')
    blocks=[]
    for name,r in series.items():
        for start,end in [('1976','1984'),('1985','1994'),('1995','2004'),('2005','2014')]:
            s=r.loc[start:end]
            blocks.append(dict(strategy=name,period=f'{start}-{end}',months=len(s),mean_ann=s.mean()*12,vol_ann=s.std(ddof=1)*np.sqrt(12)))
        s=r[r.index.year!=2008]
        blocks.append(dict(strategy=name,period='All except 2008 (noncontiguous diagnostic)',months=len(s),mean_ann=s.mean()*12,vol_ann=s.std(ddof=1)*np.sqrt(12)))
    pd.DataFrame(blocks).to_csv(OUT/'subperiods.csv',index=False)
    old=pd.read_csv(ROOT/'output/construction/monthly_returns_research.csv',index_col=0)
    old.index=pd.PeriodIndex(old.index,freq='M')
    difference=returns.RL-old.RL
    changes=pd.DataFrame({'previous_return':old.RL,'strategy_return':returns.RL,'difference':difference})
    changes=changes[difference.abs()>1e-12]
    changes.to_csv(OUT/'source_rule_changes.csv')
    first_er=str(schedule.loc[schedule.source.eq('ER'),'month'].iloc[0])
    evidence=dict(signal_and_covariance_information_lag=base['information_lag_months'],source_decision_lag=2,
                  source_switch_month=first_er,changed_RL_returns=len(changes),maximum_RL_change=float(difference.abs().max()),
                  source_known_before_all_holding_months=bool((known.to_numpy()<returns.index.to_timestamp().to_numpy()).all()),
                  current_return_used_by_position_policy=False,
                  same_endpoint_execution_remains_idealized=True,vendor_point_in_time_adjustments_verified=False,
                  out_of_sample_data_tested=False,
                  frozen_config_sha256=hashlib.sha256((ROOT/'config/risk_config.json').read_bytes()).hexdigest())
    (OUT/'summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
    primary=metrics[(metrics.information_lag_months==1)&(metrics.strategy=='trend')].iloc[0]
    delayed=metrics[(metrics.information_lag_months==2)&(metrics.strategy=='trend')].iloc[0]
    a=pd.DataFrame(alphas).iloc[0]
    body=f'''# Timing audit and OOS assessment

The implementation has past-only signal, risk and trading rules under the stated monthly endpoint convention. That is not a certificate that the vendor dataset or same-close fills are historically executable.

## Issue found and corrected

The old source mapping chose RL or ER using the **current month's** available realized return. The simulator passed the resulting source-switch flag to the fee-aware position policy. That let contemporaneous return metadata influence current position sizing; the prior tests covered forecasts but did not cover this whole path. It also assumed an RL→ER continuation was known in advance without an as-of record.

The strategy now uses a separate, deterministic source rule: retain RL until ER has 36 consecutive monthly returns available through at least t−2, then use ER permanently. This switches in **{first_er}**, before RL's later disappearance, without consulting that disappearance or current-period P&L. The change affects {len(changes)} monthly RL-column returns. [Exact changes](../output/timing_audit/source_rule_changes.csv) preserve the comparison with the original reproduced/research returns. Source labels are defined independently of missing realized P&L. The original CSV reproduction is untouched.

Policy-aware source costs now require known-at dates strictly before the holding month; missing or future dates raise an error. The source rule itself is implemented and tested from prior observations. The label column alone is not treated as proof of historical availability. The fixed source-choice policy is shared by all risk variants and never fitted to their performance.

## What is checked

- Signals, eligibility, volatility and covariance use t−1 or earlier; each forecast exports its actual information cutoff. No full-sample volatility, centered window or future-completeness filter enters trading.
- Source choice uses only observations through t−2. Current realized missingness cannot trigger a favorable source fallback; a missing held return fails explicitly.
- Band decisions use carried holdings, past-derived targets and covariance, and predetermined cost/source information. Current realized returns enter P&L only after those decisions.
- Future-data mutation tests cover the entire pipeline across three risk models and three band settings, including executed positions and prior P&L. Prefix replay reproduces the full-run history without access to its future. Terminal liquidation is disabled for replay so a changed artificial end date does not create a false mismatch.
- Missing calendar rows and zero information lags are rejected. Existing checks cover accounting, after-cost limits and the nine original baseline/cost runs.

[Validation record](../output/risk/validation.json) lists the current test count and code hashes. [Source schedule](../output/construction/strategy_source_schedule.csv) and [audit summary](../output/timing_audit/summary.json) record the timing evidence.

## Performance after the correction

The current baseline result is {primary.mean_ann:.2%} annual arithmetic mean, {primary.vol_ann:.2%} volatility, and {primary.max_drawdown:.2%} worst drawdown at 5 bps. Alpha against matching STATIC is {a.alpha_ann:.2%}, with a 95% HAC interval [{a.alpha_ci_low_ann:.2%}, {a.alpha_ci_high_ann:.2%}]. See the refreshed [brief report](../REPORT.md).

Using one additional full month of signal/risk delay gives **{delayed.mean_ann:.2%} mean, {delayed.vol_ann:.2%} volatility and {delayed.max_drawdown:.2%} drawdown**. This is a conservative timing sensitivity, not a realistic next-session fill simulation. It does not remove the assumption of executing the monthly rebalance at the valuation endpoint; that remains unverified.

## How promising is it?

Worth further research, but insufficient to predict good OOS performance. Positive results across nearby parameter choices and a simple trend signal are encouraging. However, risk forecasts underestimate realized fluctuations, the trading-band cost saving is modest, execution/funding conventions are idealized, and the historical sample has been examined repeatedly. Positive in-sample HAC alpha does not account for all strategy-selection bias and does not guarantee future profits. STATIC is only one benchmark; alpha against it does not establish unique skill relative to other trend strategies.

[Subperiods](../output/timing_audit/subperiods.csv), including an exclusion of 2008, are descriptive stability checks. **None is a fresh OOS test.** Repartitioning already-inspected years does not make them untouched. The extra-delay comparison is also a sensitivity, not OOS.

Freeze this corrected specification, obtain unexamined post-2014 data with documented roll/FX/contract conventions, run the fixed model once, and then monitor a forward paper-trading period. Evaluate risk calibration, costs and drawdowns alongside returns; do not select the best parameters after seeing the holdout. The current data cannot supply that evidence.

## Remaining limits on a no-lookahead claim

The source vendor's vintage-adjusted price history and point-in-time instrument universe are unavailable. Retrospective calendar corrections and fixed metadata exclusions are documented, but cannot independently certify the data as it would have appeared in real time. Back-adjusted futures prices can change earlier percentage returns when later rolls occur. No code-only test can rule that out without vendor methodology or archived vintages. Same-endpoint decisions/fills need next-session execution accounting to validate live feasibility.

Independent research supports the broad trend-following idea, not this exact implementation: [Hurst, Ooi and Pedersen, A Century of Evidence on Trend-Following Investing](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf). Repeated model selection can inflate backtest evidence: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

Reproduce: `python run_research.py`, `python scripts/audit_timing.py`, and `python -m pytest -q` from the project directory.
'''
    (ROOT/'docs/LOOKAHEAD_AUDIT.md').write_text(body)
    print(metrics[['information_lag_months','strategy','mean_ann','vol_ann','max_drawdown']].to_string(index=False))
    print(evidence)


if __name__=='__main__':main()
