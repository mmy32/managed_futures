import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

STATE=json.loads(Path('/private/tmp/qps-cost-revision-state.json').read_text())
STAGE=Path(STATE['stage'])
sys.path[:0]=[str(STAGE),str(STAGE/'scripts')]
from run_risk_research import evaluate, strategy_builders, write_attribution
from compare_risk_models import compare, load_inputs
from src.backtest.research_spec import primary_key
from src.config import QPS_OUTPUT_DIR, CONFIG_DIR
from src.data_loader import load_asset_map
from src.data_processing.strategy_inputs import load_strategy_inputs

settings=json.loads((CONFIG_DIR/'risk_config.json').read_text())
base=json.loads((STAGE/settings['base_config']).read_text())
meta=load_asset_map()
_, source, known, _=load_strategy_inputs(settings)
classes=[]; comparisons=[]; checks=[]
for variant,folder in [('baseline','endpoint_sensitivity'),('v2','endpoint_sensitivity_v2')]:
    out=QPS_OUTPUT_DIR/folder
    returns=pd.read_csv(out/'returns_used.csv',index_col=0)
    returns.index=pd.PeriodIndex(returns.index,freq='M')
    build,_=strategy_builders(variant)
    targets,covariance,_=build(returns,meta,base,settings)
    sample=returns.loc[base['start']:base['end']]
    one=dict(settings,primary_cost_bps=1,cost_scenarios_bps=[1],bands=[.1])
    supplement=QPS_OUTPUT_DIR/'attribution_1bps'/variant
    supplement.mkdir(parents=True,exist_ok=True)
    metrics,alphas,ledgers,details,gross,failures=evaluate(sample,source.loc[sample.index],known.loc[sample.index],targets,covariance,one,supplement)
    assert not failures
    write_attribution(ledgers,gross,details,covariance,meta,one,supplement)
    for name,ledger in ledgers.items():
        saved=pd.read_csv(out/f'{name}_ledger.csv',index_col=0)
        np.testing.assert_allclose(ledger.to_numpy(dtype=float),saved.to_numpy(dtype=float),rtol=1e-10,atol=1e-12)
    table=pd.read_csv(out/'comparison.csv').assign(variant=variant)
    for row in table.itertuples():
        key=f'correlated_band{round(row.band*100):02d}_{row.cost_bps:g}bps_{row.strategy}'
        ledger=pd.read_csv(out/f'{key}_ledger.csv',index_col=0)
        np.testing.assert_allclose(ledger.net_return,ledger.gross_return+ledger.collateral_income-ledger.cost,rtol=1e-10,atol=1e-12)
        np.testing.assert_allclose(ledger.cost,ledger.turnover*row.cost_bps/10000,rtol=1e-10,atol=1e-12)
        np.testing.assert_allclose(ledger.nav_end,(1+ledger.net_return).cumprod(),rtol=1e-10,atol=1e-12)
        assert len(ledger)==468 and not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
        comparisons.append({**row._asdict(),'gross_mean_ann':ledger.gross_return.mean()*12,'gross_cagr':(1+ledger.gross_return).prod()**(12/len(ledger))-1})
        checks.append(dict(variant=variant,run=key,months=len(ledger),accounting=True,linear_cost=True,nav=True,limits=True))
    for cost,location in [(1,supplement),(2,out)]:
        for strategy in ['trend','static']:
            gross=pd.read_csv(location/f'correlated_{strategy}_gross_attribution.csv',index_col=0)
            costs=pd.read_csv(location/f'correlated_{strategy}_instrument_costs.csv',index_col=0)
            ledger=pd.read_csv(out/f'{primary_key(dict(settings,primary_cost_bps=cost),strategy)}_ledger.csv',index_col=0)
            labels=meta.AssetClass.reindex(gross.columns)
            assert labels.notna().all()
            class_gross=gross.T.groupby(labels).sum().T
            class_cost=costs.T.groupby(labels).sum().T
            np.testing.assert_allclose((class_gross-class_cost).sum(axis=1),ledger.net_return,rtol=1e-10,atol=1e-12)
            for group in class_gross:
                classes.append(dict(variant=variant,cost_bps=cost,band=.1,strategy=strategy,asset_class=group,gross_mean_ann=class_gross[group].mean()*12,cost_mean_ann=class_cost[group].mean()*12,net_mean_ann=(class_gross[group]-class_cost[group]).mean()*12))
combined=pd.DataFrame(comparisons).drop(columns='Index')
assert len(combined)==32
combined.to_csv(QPS_OUTPUT_DIR/'cost_comparison.csv',index=False)
pd.DataFrame(classes).to_csv(QPS_OUTPUT_DIR/'class_cost_comparison.csv',index=False)
(QPS_OUTPUT_DIR/'cost_validation.json').write_text(json.dumps(dict(runs=checks,all_32_passed=True,class_contributions_reconciled=True),indent=2)+'\n')
print('All 32 runs reconcile; class contributions computed at 1 and 2 bps.',flush=True)
inputs=load_inputs()
variants=json.loads((CONFIG_DIR/'risk_model_comparison.json').read_text())['variants']
risk=[]
for cost in [1,2]:
    table=compare(inputs,variants,dict(settings,primary_cost_bps=cost))
    risk.append(table)
    print('Estimator sensitivity completed at',cost,'bps',flush=True)
pd.concat(risk,ignore_index=True).to_csv(QPS_OUTPUT_DIR/'risk_model_comparison/cost_comparison.csv',index=False)
print('SUPPLEMENTARY DIAGNOSTICS COMPLETE',flush=True)
