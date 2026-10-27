"""Controlled rerun in a disposable copy; original reports are read-only references."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/Users/anaybhat/Documents/managed_futures')
STATE = json.loads(Path('/private/tmp/qps-cost-revision-state.json').read_text())
STAGE = Path(STATE['stage'])
OUT = STAGE / 'reports/qps_baseline/output'
CONFIG = STAGE / 'config/risk_config.json'
ACTIVE_CONFIG = CONFIG.read_text()
LOGS = STAGE / 'execution_logs'
LOGS.mkdir(exist_ok=True)
ENV = dict(os.environ, PYTHONPATH=str(STAGE), MPLCONFIGDIR='/private/tmp/qps-step2-matplotlib')


def run(name, script, *args, expected=0):
    command = ['/opt/anaconda3/bin/python', str(STAGE / 'scripts' / script), *args]
    print('RUN', name, flush=True)
    with (LOGS / f'{name}.log').open('w') as stream:
        result = subprocess.run(command, cwd=STAGE, env=ENV, stdout=stream, stderr=subprocess.STDOUT)
    with (LOGS / 'commands.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(name=name, command=command, cwd=str(STAGE), returncode=result.returncode))+'\n')
    if result.returncode != expected:
        raise RuntimeError(f'{name}: exit {result.returncode}; see {LOGS / (name + ".log")}')
    print('PASS', name, flush=True)


def compare_file(new, saved):
    current, prior = pd.read_csv(new), pd.read_csv(saved)
    pd.testing.assert_frame_equal(current, prior, check_exact=False, rtol=1e-10, atol=1e-12)
    numeric = current.select_dtypes('number').columns
    delta = (current[numeric] - prior[numeric]).abs().to_numpy()
    return float(np.nanmax(delta)) if delta.size else 0.0


run('reconstruct_monthly', 'construct_returns.py')
construction_delta = compare_file(OUT / 'construction/monthly_returns_research.csv', ROOT / 'reports/qps_baseline/output/construction/monthly_returns_research.csv')
run('validate', 'run_research.py', '--validate')
checks = []
try:
    for variant, folder in [('baseline','endpoint_sensitivity'),('v2','endpoint_sensitivity_v2')]:
        original = ROOT / 'reports/qps_baseline/output' / folder
        settings = json.loads((original / 'manifest.json').read_text())['config']
        CONFIG.write_text(json.dumps(settings, indent=2)+'\n')
        run(f'reference_{variant}', 'run_risk_research.py', '--variant', variant, '--endpoint-sensitivity')
        names = ['comparison.csv','alpha.csv','returns_used.csv']
        names += [p.name for p in original.glob('*_ledger.csv')]
        for name in names:
            checks.append(dict(variant=variant, file=name, max_abs_difference=compare_file(OUT/folder/name, original/name)))
        destination = STAGE / 'reference_reproduction' / variant
        shutil.copytree(OUT/folder, destination)
finally:
    CONFIG.write_text(ACTIVE_CONFIG)
(STAGE / 'reference_reproduction/checks.json').write_text(json.dumps(dict(construction_max_abs_difference=construction_delta, relative_tolerance=1e-10, absolute_tolerance=1e-12, checks=checks),indent=2)+'\n')
for variant in ['baseline','v2']:
    run(f'preserved_{variant}', 'run_risk_research.py', '--variant', variant, expected=2)
    run(f'cost_revision_{variant}', 'run_risk_research.py', '--variant', variant, '--endpoint-sensitivity')
    report = 'REPORT.md' if variant=='baseline' else 'REPORT_V2.md'
    run(f'export_{variant}', 'export_report.py', '--report', report)
print('CONTROLLED COMPARISON COMPLETE', flush=True)
