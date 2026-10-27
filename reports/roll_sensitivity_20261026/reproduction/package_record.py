import hashlib,json,platform,re,shutil,subprocess,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
from xml.etree import ElementTree
import numpy as np,pandas as pd,statsmodels
root=Path('/Users/anaybhat/Documents/managed_futures'); dest=root/'reports/roll_sensitivity_20261026'; ref=root/'reports/cost_revision_20261026'; band=root/'reports/band_experiment_20261026'
repro=dest/'reproduction';repro.mkdir(exist_ok=True)
logs=dest/'execution_logs';logs.mkdir(exist_ok=True)
for name in ['qps_step4_run.log','qps_step4_targeted.log','qps_step4_roll_tests.log','qps_step4_pytest.log','qps_step4_pytest.xml','qps_step4_mypy.log']:
 shutil.copy2(Path('/private/tmp')/name,logs/name)
shutil.copy2('/private/tmp/qps_step4_report.py',repro/'generate_report_record.py')
shutil.copy2('/private/tmp/qps_step4_package.py',repro/'package_record.py')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
source=[]
for folder,pattern in [('src','*.py'),('scripts','*.py'),('tests','*.py'),('config','*.json'),('docs','*.md')]:source.extend(sorted((root/folder).rglob(pattern)))
source += [root/'README.md',root/'pyproject.toml',root/'.gitignore']
hashes={str(p.relative_to(root)):digest(p) for p in source}
with zipfile.ZipFile(repro/'source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as archive:
 for p in source:archive.write(p,str(p.relative_to(root)))
(repro/'source_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
inputs=dest/'inputs';inputs.mkdir(exist_ok=True)
paths={
 'returns_used.csv':ref/'output/endpoint_sensitivity_v2/returns_used.csv',
 'strategy_source.csv':ref/'output/construction/strategy_source.csv',
 'strategy_source_known_at.csv':ref/'output/construction/strategy_source_known_at.csv',
 'AssetMapCsv.csv':root/'data/raw/AssetMapCsv.csv',
 'baseline_config.json':root/'config/baseline_config.json',
 'production_risk_config.json':root/'config/risk_config.json',
 'qps_v2.json':root/'config/qps_v2.json',
 'roll_sensitivity.json':root/'config/roll_sensitivity.json',
 'endpoint_assumption.json':ref/'output/endpoint_sensitivity_v2/assumption.json',
}
for name,p in paths.items():shutil.copy2(p,inputs/name)
suites=ElementTree.parse(logs/'qps_step4_pytest.xml').getroot().iter('testsuite')
totals={k:0 for k in ['tests','failures','errors','skipped']}
for suite in suites:
 for k in totals:totals[k]+=int(suite.attrib.get(k,0))
assert totals['tests']==167 and totals['failures']==totals['errors']==0
(dest/'test_validation.json').write_text(json.dumps(dict(command='/opt/anaconda3/bin/python -m pytest -q --junitxml=/private/tmp/qps_step4_pytest.xml',cwd=str(root),**totals,source_hashes=hashes),indent=2)+'\n')
old=json.loads((ref/'provenance.json').read_text())
for package in [ref,band]:
 for name,expected in json.loads((package/'ARTIFACT_SHA256.json').read_text()).items():assert digest(package/name)==expected,name
for collection in [old['raw_hashes'],old['preserved_historical_hashes']]:
 for name,expected in collection.items():assert digest(root/name)==expected,name
assert digest(root/'config/risk_config.json')==json.loads((band/'reproduction/source_hashes.json').read_text())['config/risk_config.json']
provenance=dict(created_utc=datetime.now(timezone.utc).isoformat(),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),working_tree_changes=True,command='PYTHONPATH=. /opt/anaconda3/bin/python -u scripts/run_roll_sensitivity.py --reference reports/cost_revision_20261026 --output reports/roll_sensitivity_20261026/output',reference_manifest_sha256=digest(ref/'ARTIFACT_SHA256.json'),band_manifest_sha256=digest(band/'ARTIFACT_SHA256.json'),inputs={name:dict(source=str(p.relative_to(root)),sha256=digest(p)) for name,p in paths.items()},versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,statsmodels=statsmodels.__version__),raw_files_unchanged=65,historical_report_files_unchanged=241,earlier_experiment_packages_unchanged=True,production_config_unchanged=True,observed_roll_history_available=False,scope='Step 4 only; 36 hypothetical roll-calendar scenarios, no liquidity/funding extension')
(dest/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
(dest/'REPRODUCE.md').write_text('''# Reproducing Step 4

This release is an assumption-based monthly roll-cost sensitivity, not reconstructed contract history. The data audit and observed-data gate are recorded in `output/data_gate.json` and `output/contract_data_audit.csv`. No primary roll schedule was adopted.

Use a disposable copy of the repository with the Step 2 package and raw inputs present. Overlay `reproduction/source_snapshot.zip` for the exact source/config version and install dependencies from `pyproject.toml`. The source hashes and library versions are recorded. From that copy's root:

```sh
PYTHONPATH=. python scripts/run_roll_sensitivity.py \\
  --reference reports/cost_revision_20261026 \\
  --output reports/new_roll_run/output
python -m pytest -q
```

The runner refuses an existing output directory, verifies the Step 2 artifacts and 65 raw hashes, audits all daily schemas and the workbook, and records the fixed assumptions before simulation. `config/roll_sensitivity.json` defines regular 1/2 bps, complete-roll 1/2 bps, three quarterly phases and monthly rolls at the retained 10% band. Four trade-only controls plus 32 roll cases produce the 36-case comparison.

`RollSchedule` requires a boolean monthly schedule with known-at dates before each relevant holding month. These scenario calendars are deliberately fixed before the sample. They are not empirical knowledge of actual contracts. For hypothetical monthly execution, same-direction overlap is rolled at the beginning of the period, with ordinary net resizes charged separately. Source close/open trades supersede coincident assumed rolls. Fees enter `BandPolicy` and the limit solver before executed holdings and NAV are finalized.

Roll bps describe the complete close/open on matched notional. Explicit per-leg input is converted by multiplying the rate by two. The event journal splits complete-roll fees equally across matched close/open legs. Entry/exit/reversal and source-switch trades retain ordinary per-side costs. Final liquidation is an ordinary end-period exit. Economic carry and continuous-price adjustments are not fee components.

Each run exports a monthly ledger, compressed dated event journal (`*_events.csv.gz`), compressed executed exposure panel and class contribution table. Journal notional and costs reconcile to the ledger; class gross contributions less both fee components reconcile to net return. All four trade-only controls match Step 2 within absolute tolerance 1e-12 and relative tolerance 1e-10. The optional schedule is inactive by default, preserving the existing production strategy.

The final suite passes **167 tests**. Modified/new Python files pass Ruff. Full mypy still reports the pre-existing slice-index error at `src/portfolio_construction/targets.py:44`; that file was not changed. Execution and test logs are retained. `generate_report_record.py` and `package_record.py` record the presentation/packaging steps with their original machine-specific paths; numerical reproduction uses the portable command above.

Raw inputs, original Downloads files and previous result packages are retained. Scratch work and disposable caches are listed in `cleanup.json`; they are not runtime dependencies of this package. Source and artifact hashes allow integrity checks after cleanup. No commit or push was made. Step 5 has not started.
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
artifact={str(p.relative_to(dest)):digest(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='ARTIFACT_SHA256.json'}
(dest/'ARTIFACT_SHA256.json').write_text(json.dumps(artifact,indent=2)+'\n')
print('Packaged',len(artifact),'files;',len(source),'source files; prior artifacts, raw data and production config verified unchanged.')
