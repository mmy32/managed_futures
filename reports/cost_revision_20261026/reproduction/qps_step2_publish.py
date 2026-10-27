import hashlib,json,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd

root=Path('/Users/anaybhat/Documents/managed_futures')
state=json.loads(Path('/private/tmp/qps-cost-revision-state.json').read_text()); stage=Path(state['stage'])
report=stage/'reports/qps_baseline'; source=report/'output'
dest=root/'reports/cost_revision_20261026'
assert not dest.exists(), 'Do not overwrite an existing cost-revision release'
dest.mkdir(parents=True)
for name in ['REPORT.md','REPORT.html','REPORT_V2.md','REPORT_V2.html','ENDPOINT_SENSITIVITY.md','ENDPOINT_SENSITIVITY.html','ENDPOINT_SENSITIVITY_V2.md','ENDPOINT_SENSITIVITY_V2.html']:
 shutil.copy2(report/name,dest/name)
for name in ['endpoint_sensitivity','endpoint_sensitivity_v2','risk','risk_v2','construction','attribution_1bps']:
 shutil.copytree(source/name,dest/'output'/name)
for name in ['cost_comparison.csv','class_cost_comparison.csv','cost_validation.json']:
 shutil.copy2(source/name,dest/'output'/name)
model_dest=dest/'output/risk_model_comparison'; model_dest.mkdir()
shutil.copy2(source/'risk_model_comparison/cost_comparison.csv',model_dest/'cost_comparison.csv')
shutil.copytree(stage/'execution_logs',dest/'execution_logs')
reference=dest/'reference_reproduction';reference.mkdir()
shutil.copy2(stage/'reference_reproduction/checks.json',reference/'checks.json')
for variant,folder in [('baseline','endpoint_sensitivity'),('v2','endpoint_sensitivity_v2')]:
 d=reference/variant; d.mkdir()
 original=root/'reports/qps_baseline/output'/folder
 for name in ['comparison.csv','alpha.csv','manifest.json']:
  shutil.copy2(stage/'reference_reproduction'/variant/name,d/name)
  shutil.copy2(original/name,d/f'original_{name}')
 for p in (stage/'reference_reproduction'/variant).glob('*_5bps_*_ledger.csv'):shutil.copy2(p,d/p.name)
 for name in ['config','base_config']:
  value=json.loads((original/'manifest.json').read_text())[name]
  (d/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
provenance=dict(run_id=dest.name,created_utc=datetime.now(timezone.utc).isoformat(),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),working_tree_changes=True,stage=str(stage),raw_source=state['source'],raw_hashes=state['raw_hashes'],preserved_historical_hashes=state['historical_hashes'],required_raw_files_matching_original_manifest=65,missing_optional_archive='FuturesUnderlyingData.zip (extracted files verified; archive not consumed)',grid=dict(variants=['baseline','v2'],strategies=['trend','static'],bands=[0,.1],costs_bps=[0,1,2,5]),primary=dict(band=.1,cost_bps=2),conditional_endpoint_assumption=True,legacy_2000_2014_replay='Historical record retained; not rerun because archived input configs are absent. The 1976–2014 baseline/v2 reference was reproduced in this release.')
(dest/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
for name in ['DATA_STATUS.md','DATA_STATUS_V2.md']:
 (dest/'supporting_docs').mkdir(exist_ok=True)
 shutil.copy2(stage/'docs'/name,dest/'supporting_docs'/name)
for p in dest.glob('*.md'):
 s=p.read_text()
 for name in ['DATA_STATUS.md','DATA_STATUS_V2.md']:
  s=s.replace(f'../../docs/{name}',f'supporting_docs/{name}')
 p.write_text(s)

def table(headers,rows):
 return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(str,row))+' |' for row in rows])
metrics=pd.read_csv(dest/'output/cost_comparison.csv')
main=metrics.query('band == .1 and cost_bps in [1,2]')
rows=[]
for variant in ['baseline','v2']:
 for r in main.query('variant == @variant and strategy == "trend"').itertuples():
  rows.append([variant.upper()+' TREND',r.cost_bps,f'{r.cagr:.2%}',f'{r.sharpe:.3f}',f'{r.max_drawdown:.2%}',f'{r.mean_cost_ann:.3%}'])
for r in main.query('variant == "v2" and strategy == "static"').itertuples():
 rows.append(['Matching STATIC',r.cost_bps,f'{r.cagr:.2%}',f'{r.sharpe:.3f}',f'{r.max_drawdown:.2%}',f'{r.mean_cost_ann:.3%}'])
v2=metrics.query('variant == "v2" and strategy == "trend" and band == .1').set_index('cost_bps')
class_table=pd.read_csv(dest/'output/class_cost_comparison.csv').query('variant == "v2" and cost_bps == 2 and strategy == "trend"')
class_rows=[[r.asset_class,f'{r.gross_mean_ann:.3%}',f'{r.cost_mean_ann:.3%}',f'{r.net_mean_ann:.3%}'] for r in class_table.itertuples()]
risk=pd.read_csv(model_dest/'cost_comparison.csv')
risk_rows=[]
for name in risk.estimator.drop_duplicates():
 subset=risk.query('estimator == @name and strategy == "trend"').set_index('cost_bps')
 risk_rows.append([name,f'{subset.loc[1,"sharpe"]:.3f}',f'{subset.loc[2,"sharpe"]:.3f}',f'{subset.loc[2,"max_drawdown"]:.2%}',f'{subset.loc[2,"realized_predicted_ratio"]:.3f}'])
summary=f'''# Step 2: controlled transaction-cost comparison

Completed 26 October 2026. **Primary cost: 2 bps; sensitivity: 1 bps. Step 3 has not started.**

Lower assumed trading costs improve net returns modestly. They do not change the signals, the 36-month risk estimator or the adopted 10% trading band. The results remain in-sample and **conditional on the unverified March 1997 endpoint assumption**. The preserved-policy runs still fail on missing held returns.

## What was run

The original 65 input files were restored byte-for-byte from the team's local course-data folder: asset map, monthly returns, benchmark workbook and 62 daily files. Each matches its historical manifest hash. Monthly reconstruction matches the saved research panel. The optional source ZIP is absent; its extracted daily files are verified.

The existing 1976–2014 baseline and v2 configurations were reproduced first: 24 historical runs at 0/5/10 bps, including both bands and both strategies. All 30 file comparisons (ledgers, metric tables, alphas and return panels) pass numerical tolerances; the largest absolute difference is 2.21e-13. [Reference checks](reference_reproduction/checks.json).

The new controlled grid has **32 runs**: baseline/v2 × TREND/STATIC × 0/1/2/5 bps × 0/10% bands. All use the same 468 months, data scenario, signals and risk rules. Every path was resimulated, including fee feedback into NAV, carried holdings and limits. Costs are charged per unit of absolute one-way traded notional / beginning-period NAV; turnover is not halved.

## Main results at the adopted 10% band

{table(['Portfolio','Cost (bps)','CAGR','Net Sharpe','Max drawdown','Annual direct cost drag'],rows)}

STATIC is identical across the two versions and is shown once. CAGR is compounded growth; direct cost drag is 12 times mean monthly booked costs, not the difference between gross and net CAGR.

For v2 TREND, moving from 5 to 2 bps raises CAGR from {v2.loc[5,'cagr']:.2%} to {v2.loc[2,'cagr']:.2%} and Sharpe from {v2.loc[5,'sharpe']:.3f} to {v2.loc[2,'sharpe']:.3f}. Annual direct cost drag falls from {v2.loc[5,'mean_cost_ann']:.3%} to {v2.loc[2,'mean_cost_ann']:.3%}, a saving of {(v2.loc[5,'mean_cost_ann']-v2.loc[2,'mean_cost_ann'])*10000:.2f} bps of NAV per year. At 1 bps, CAGR is {v2.loc[1,'cagr']:.2%} and direct drag is {v2.loc[1,'mean_cost_ann']:.3%}.

The baseline/v2 ranking is descriptive: the FX blend was selected after inspecting this history. Lower costs do not supply independent evidence for the signal choice.

## V2 class contributions at 2 bps

{table(['Class','Gross annual mean contribution','Annual cost contribution','Net annual mean contribution'],class_rows)}

These contributions sum to the portfolio's arithmetic mean and costs. They are not class CAGRs. [Both versions and both 1/2 bps cases](output/class_cost_comparison.csv).

## Risk-estimator sensitivity, with the cost cases held explicit

The existing six-estimator diagnostic was refreshed at 1 and 2 bps, retaining its original window, shrinkage, signals and 10% band. These are additional exploratory runs, separate from the 32-case controlled grid.

{table(['Estimator','TREND Sharpe, 1 bps','TREND Sharpe, 2 bps','Drawdown, 2 bps','Calibration, 2 bps'],risk_rows)}

Calibration is the SD of gross returns divided by their prior forecast volatility; 1 is ideal. Faster estimators still underpredict risk and do not dominate on drawdown. Keep the existing equal-weight 36-month estimator. This is an inspected six-way in-sample comparison, not a new validation or an adopted enhancement. [Full TREND/STATIC table](output/risk_model_comparison/cost_comparison.csv).

## Validation and qualifications

- **140 tests passed** against the final source snapshot. Every new run reconciles gross return plus cash income minus costs to net return, linear charges to actual turnover, and NAV to compounding. No rebalance risk/gross-limit breaches occur. Class contributions reconcile at both 1 and 2 bps. [Checks](output/cost_validation.json).
- All 65 raw files and all 241 historical report/output files remain unchanged. Reference manifests, source hashes and execution logs are preserved separately in this release.
- The 12-run 2000–2014 replay mentioned in older reports is a historical validation record; its archived input configs are absent, so it was not rerun here. This release independently reproduces the full 1976–2014 baseline/v2 reference.
- Regular expiry-roll activity, calibrated spread/impact and executable endpoint fills remain unresolved. The 1–2 bps charge is an aggregate assumption, not a fitted execution model.
- The FX description now correctly states that opposite signs produce zero exposure; half exposure requires one zero sign. No signal calculation changed.

## Files and next step

- [V2 presentation report](REPORT_V2.md) · [standalone HTML](REPORT_V2.html)
- [Baseline presentation report](REPORT.md) · [standalone HTML](REPORT.html)
- [All 32 scenarios, including gross/net metrics](output/cost_comparison.csv)
- [Baseline preserved-policy status](supporting_docs/DATA_STATUS.md) · [v2 status](supporting_docs/DATA_STATUS_V2.md)
- [Provenance](provenance.json) · [Reproduction instructions](REPRODUCE.md)

**Stop here.** Step 3 will test the predeclared 0/5/10% bands at 1 and 2 bps. The 5% strategy experiment has not been run or adopted.
'''
(dest/'SUMMARY.md').write_text(summary)
print('Published isolated results to',dest)
