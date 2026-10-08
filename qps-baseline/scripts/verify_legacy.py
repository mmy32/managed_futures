"""Replay the archived 2000–2014 comparison before extending the evaluation."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from backtest import simulate
from risk_model import build_forecasts, BandPolicy
from strategy_inputs import load_strategy_inputs

ROOT = Path(__file__).resolve().parents[1]


def main():
    archive = ROOT/'output/legacy_2000_2014'
    base = json.loads((archive/'baseline_config.json').read_text())
    settings = json.loads((archive/'risk_config.json').read_text())
    returns, source, known, _ = load_strategy_inputs(settings)
    meta = pd.read_csv(ROOT/'data/AssetMapCsv.csv').set_index('ID')
    targets, covariance, _ = build_forecasts(returns, meta, base, settings)
    sample = returns.loc[base['start']:base['end']]
    comparisons = []
    for band in [0., .1]:
        for cost in [0, 5, 10]:
            for strategy in ['trend', 'static']:
                ledger, _ = simulate(sample, targets[strategy], cost, source.loc[sample.index],
                                     position_policy=BandPolicy(covariance, settings, band),
                                     source_known_at=known.loc[sample.index])
                path = archive/f'correlated_band{round(band*100):02d}_{cost}bps_{strategy}_ledger.csv'
                old = pd.read_csv(path, index_col=0)
                old.index = pd.PeriodIndex(old.index, freq='M')
                assert ledger.index.equals(old.index)
                delta = 0.
                for col in old:
                    np.testing.assert_allclose(ledger[col], old[col], atol=2e-10, rtol=1e-10, err_msg=f'{path.name}: {col}')
                    delta = max(delta, float(np.max(np.abs(ledger[col].astype(float)-old[col].astype(float)))))
                comparisons.append(dict(run=path.stem, months=len(old), columns=len(old.columns), maximum_absolute_difference=delta,
                                        reference_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result = dict(passed=True, runs=len(comparisons), start=base['start'], end=base['end'], comparisons=comparisons)
    (ROOT/'output/risk/legacy_reproduction.json').write_text(json.dumps(result, indent=2)+'\n')
    print(f'Original-period replay: {len(comparisons)} runs agree; max difference {max(x["maximum_absolute_difference"] for x in comparisons):.3g}')


if __name__ == '__main__':
    main()
