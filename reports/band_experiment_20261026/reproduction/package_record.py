import hashlib,json,os,platform,re,shutil,subprocess,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree
import numpy as np,pandas as pd,statsmodels
root=Path('/Users/anaybhat/Documents/managed_futures'); dest=root/'reports/band_experiment_20261026'; reference=root/'reports/cost_revision_20261026'
repro=dest/'reproduction';repro.mkdir(exist_ok=True)
logs=dest/'execution_logs';logs.mkdir(exist_ok=True)
for name in ['qps_step3_run.log','qps_step3_pytest.log','qps_step3_pytest.xml','qps_step3_mypy.log']:
 shutil.copy2(Path('/private/tmp')/name,logs/name)
shutil.copy2('/private/tmp/qps_step3_report.py',repro/'generate_report_record.py')
shutil.copy2('/private/tmp/qps_step3_package.py',repro/'package_record.py')
(repro/'check_reversals.py').write_text('''"""Supplemental same-month direction check; pass an experiment output directory."""
import sys
from pathlib import Path
import pandas as pd
out = Path(sys.argv[1])
target = pd.read_csv(out / "trend_targets.csv", index_col=0)
events = (target * target.shift(1)).lt(0)
rows = []
for file in sorted(out.glob("*_trend_exposure.csv")):
    exposure = pd.read_csv(file, index_col=0)
    mismatches = int((events & (exposure * target).le(0)).to_numpy().sum())
    assert mismatches == 0
    count = int(events.to_numpy().sum())
    rows.append(dict(run=file.name.removesuffix("_exposure.csv"), target_reversals=count,
                     same_month_direction_matches=count-mismatches, direction_mismatches=mismatches))
pd.DataFrame(rows).to_csv(out / "reversal_execution.csv", index=False)
''')
inputs=dest/'inputs';inputs.mkdir(exist_ok=True)
input_files={
 'returns_used.csv':reference/'output/endpoint_sensitivity_v2/returns_used.csv',
 'strategy_source.csv':reference/'output/construction/strategy_source.csv',
 'strategy_source_known_at.csv':reference/'output/construction/strategy_source_known_at.csv',
 'AssetMapCsv.csv':root/'data/raw/AssetMapCsv.csv',
 'baseline_config.json':root/'config/baseline_config.json',
 'production_risk_config.json':root/'config/risk_config.json',
 'qps_v2.json':root/'config/qps_v2.json',
 'band_experiment.json':root/'config/band_experiment.json',
 'endpoint_assumption.json':reference/'output/endpoint_sensitivity_v2/assumption.json',
}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for name,p in input_files.items():shutil.copy2(p,inputs/name)
source_files=[]
for folder,pattern in [('src','*.py'),('scripts','*.py'),('tests','*.py'),('config','*.json'),('docs','*.md')]:source_files.extend(sorted((root/folder).rglob(pattern)))
source_files += [root/'pyproject.toml',root/'README.md']
source_hashes={str(p.relative_to(root)):digest(p) for p in source_files}
with zipfile.ZipFile(repro/'source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as archive:
 for p in source_files:archive.write(p,str(p.relative_to(root)))
(repro/'source_hashes.json').write_text(json.dumps(source_hashes,indent=2)+'\n')
suites=ElementTree.parse(logs/'qps_step3_pytest.xml').getroot().iter('testsuite')
totals={k:0 for k in ['tests','failures','errors','skipped']}
for suite in suites:
 for k in totals:totals[k]+=int(suite.attrib.get(k,0))
assert totals['tests']==143 and totals['failures']==totals['errors']==0
(dest/'test_validation.json').write_text(json.dumps(dict(command='/opt/anaconda3/bin/python -m pytest -q --junitxml=/private/tmp/qps_step3_pytest.xml',cwd=str(root),**totals,source_hashes=source_hashes),indent=2)+'\n')
old=json.loads((reference/'provenance.json').read_text())
for name,expected in json.loads((reference/'ARTIFACT_SHA256.json').read_text()).items():assert digest(reference/name)==expected,name
for hashes in [old['raw_hashes'],old['preserved_historical_hashes']]:
 for name,expected in hashes.items():assert digest(root/name)==expected,name
assert digest(root/'config/risk_config.json')==json.loads((reference/'reproduction/source_hashes.json').read_text())['config/risk_config.json']
provenance=dict(created_utc=datetime.now(timezone.utc).isoformat(),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),working_tree_changes=True,command='PYTHONPATH=. /opt/anaconda3/bin/python -u scripts/run_band_experiment.py --reference reports/cost_revision_20261026 --output reports/band_experiment_20261026/output',reference_manifest_sha256=digest(reference/'ARTIFACT_SHA256.json'),inputs={k:dict(source=str(p.relative_to(root)),sha256=digest(p)) for k,p in input_files.items()},versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,statsmodels=statsmodels.__version__),production_config_unchanged=True,raw_files_unchanged=65,historical_report_files_unchanged=241,step2_artifacts_unchanged=True,scope='Step 3 only; frozen v2 inputs, 12 runs, no roll-cost work',specification_written_utc=datetime.fromtimestamp((dest/'output/trial_specification.json').stat().st_mtime,timezone.utc).isoformat())
(dest/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
(dest/'REPRODUCE.md').write_text('''# Reproducing Step 3

This is a fixed experiment on the verified conditional Step 2 return panel, not a fresh raw-data reconstruction or untouched holdout. All 65 raw hashes and all Step 2 artifact hashes were checked. The production cost remains 2 bps and the primary band remains 10%.

Use the repository with the Step 2 artifact package and raw inputs present. For exact code, overlay `reproduction/source_snapshot.zip` into a disposable copy; hashes and library versions are recorded. Install the project dependencies from `pyproject.toml`, then run from that repository root:

```sh
PYTHONPATH=. python scripts/run_band_experiment.py \\
  --reference reports/cost_revision_20261026 \\
  --output reports/new_band_run/output
python reports/band_experiment_20261026/reproduction/check_reversals.py \\
  reports/new_band_run/output
python -m pytest -q
```

The runner refuses an existing output directory. It writes the experiment specification before forecasting or simulation. `config/band_experiment.json` contains the fixed grid, four subperiods, 20,000 draws, block lengths, seed, family size and material-gain threshold. This specification was frozen before computing the new 5% cases, but all history and the 0/10% alternatives had already been inspected.

The runner records all 12 ledgers, executed exposures, instrument costs/gross contributions, turnover components, target/risk diagnostics, paired gross/cost/net decomposition, paired bootstrap intervals and subperiods. The eight common 0/10% runs are checked against Step 2. Supplemental reversal execution checks write `reversal_execution.csv`.

Every trade belongs to one category: source close/open takes precedence, followed by entries/exits, reversals or same-direction resizes; final liquidation is separate. Reconstructed previous holdings incorporate preceding instrument returns, fees and NAV drift. Component turnover and costs reconcile to the simulator. No regular-expiry roll events are inferred from the source-switch label.

`generate_report_record.py` and `package_record.py` preserve the report-generation steps with the original machine-specific paths. They can be adapted to another experiment directory; numerical reproduction uses the portable runner above. The report's final decision is an interpretation of the frozen results, not an automatic optimizer.

`test_validation.json`, execution logs, source/input hashes and `ARTIFACT_SHA256.json` record the evidence. The full test suite passed 143 tests. Changed/new Python files pass Ruff. Repository-wide mypy still reports the pre-existing slice-index error at `src/portfolio_construction/targets.py:44`; that file was not changed.

No strategy defaults were changed, no commit or push was made, and Step 4 has not started.
''')
sys.path[:0]=[str(root),str(root/'scripts')]
import export_report
export_report.QPS_REPORT_DIR=dest
export_report.main('SUMMARY.md')
missing=[]
for p in dest.glob('*.md'):
 for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not url.startswith(('http:','https:','#','mailto:')) and not (p.parent/url.split('#')[0]).exists():missing.append((p.name,url))
assert not missing,missing
assert (dest/'SUMMARY.html').read_text().count('data:image/png;base64,')==1
artifacts={str(p.relative_to(dest)):digest(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='ARTIFACT_SHA256.json'}
(dest/'ARTIFACT_SHA256.json').write_text(json.dumps(artifacts,indent=2)+'\n')
print('Step 3 package verified:',len(artifacts),'artifacts;',len(source_files),'source files; historical inputs/results unchanged.')
