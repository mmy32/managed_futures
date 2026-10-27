import hashlib,json,os,re,shutil,zipfile
from pathlib import Path
root=Path('/Users/anaybhat/Documents/managed_futures'); dest=root/'reports/cost_revision_20261026'
state=json.loads(Path('/private/tmp/qps-cost-revision-state.json').read_text());stage=Path(state['stage'])
repro=dest/'reproduction';repro.mkdir(exist_ok=True)
for name in ['qps_step2_run.py','qps_step2_diagnostics.py','qps_step2_refresh.py','qps_step2_publish.py','qps_step2_package.py']:
 shutil.copy2(Path('/private/tmp')/name,repro/name)
# Saved manifests describe the staged repository paths; freeze the actual source separately.
files=[]
for folder,pattern in [('src','*.py'),('scripts','*.py'),('tests','*.py'),('config','*.json'),('docs','*.md'),('notebooks','*.ipynb')]:
 files.extend(sorted((root/folder).rglob(pattern)))
files.extend([root/'pyproject.toml',root/'README.md'])
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with zipfile.ZipFile(repro/'source_snapshot.zip','w',zipfile.ZIP_DEFLATED) as archive:
 for p in files:archive.write(p,str(p.relative_to(root)))
(repro/'source_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
for p in (dest/'supporting_docs').glob('*.md'):
 def relink(match):
  label,url=match.groups()
  if url.startswith(('http:','https:','#','mailto:')):return match.group(0)
  target=(stage/'docs'/url).resolve()
  if target.is_relative_to(stage/'reports/qps_baseline'):
   actual=dest/target.relative_to(stage/'reports/qps_baseline')
  elif target.is_relative_to(stage):actual=root/target.relative_to(stage)
  else:return match.group(0)
  return f'[{label}]({os.path.relpath(actual,p.parent)})'
 p.write_text(re.sub(r'\[([^\]]+)\]\(([^)]+)\)',relink,p.read_text()))
(dest/'REPRODUCE.md').write_text('''# Reproducing the cost revision

This release was built in an isolated copy of the repository, not by overwriting the historical reports. The source is the working tree based on commit `3b42f39`, including the cost-configuration changes and final reporting corrections. Nothing has been committed or pushed by this step.

## Inputs and source

1. Use a disposable copy of the repository so existing research output is preserved.
2. Overlay `reproduction/source_snapshot.zip` at that copy's root. `reproduction/source_hashes.json` records every included file. The archive includes source, tests, configs, docs and notebooks; it excludes raw data.
3. Restore `data/raw/` using the 65 files listed in `provenance.json`. Every runtime input matches the historical data hashes. The missing optional ZIP is redundant with the 62 verified daily CSVs.
4. Install the dependencies in `pyproject.toml`; exact runtime library versions are in each run's `manifest.json`.

From that disposable repository, set `PYTHONPATH=.` and run:

```sh
python scripts/construct_returns.py
python scripts/run_research.py --validate
python scripts/run_risk_research.py --variant baseline
python scripts/run_risk_research.py --variant baseline --endpoint-sensitivity
python scripts/export_report.py --report REPORT.md
python scripts/run_risk_research.py --variant v2
python scripts/run_risk_research.py --variant v2 --endpoint-sensitivity
python scripts/export_report.py --report REPORT_V2.md
```

The two preserved-policy commands are expected to exit with status 2 due to missing held returns; run the conditional commands separately afterward. The primary config runs 16 cases per variant, for 32 cases total.

## Historical reproduction

Before the new-cost grid, the execution used each variant's saved settings from `reference_reproduction/<variant>/config.json` and `base_config.json`. With those settings it reran the conditional runner, then compared the complete 12-scenario ledger set plus metrics, alpha and returns with the original saved files. The 30 comparisons use absolute tolerance 1e-12 and relative tolerance 1e-10. See `reference_reproduction/checks.json`; copied original manifests and tables, plus the reproduced 5 bps ledgers, are included. Restore the new configuration from the source snapshot before running the new grid.

The historical 2000–2014 replay is not part of this execution: its original archive configs are absent. Its earlier validation record is preserved as historical evidence, rather than represented as a fresh replay.

## Additional diagnostics and provenance

`output/cost_comparison.csv` contains all 32 cases with gross/net means, gross/net CAGR, Sharpe, drawdown, turnover, costs, exposure and calibration. Gross CAGR compounds before-fee returns along each run's actual positions; it is distinct from the separately resimulated zero-cost scenario. `output/class_cost_comparison.csv` records gross, cost and net arithmetic contributions for both versions/strategies at 1 and 2 bps. Monthly instrument/class attribution files are included.

The six existing estimator alternatives were rerun at both 1 and 2 bps without adopting a new estimator. These 24 diagnostic cases are separate from the main 32-case cost grid. Four supplemental 1 bps simulations recover full instrument attribution and are checked against the corresponding main-grid ledgers.

`reproduction/qps_step2_*.py` captures the exact execution/aggregation steps, including the recorded machine-specific staging paths. To reuse those helper scripts, update their root/staging-state paths for the disposable copy; the standard research commands above need no such edits. Execution logs and `provenance.json` retain the original locations. The final source snapshot and `ARTIFACT_SHA256.json` make the code and delivered outputs independently checkable.

All original `reports/qps_baseline/` files and all raw input bytes were checked unchanged after execution. Step 3, the 5% band experiment, has not started.
''')
# Ensure final report claims match the tested source and figures are embedded for offline use.
for name in ['REPORT.md','REPORT_V2.md']:
 text=(dest/name).read_text(); assert '140 tests pass' in text
 assert '**2 bps per unit of one-way' in text
 assert 'half size when they differ' not in text
 html=(dest/name.replace('.md','.html')).read_text()
 assert html.count('data:image/png;base64,')==5
for group in ['raw_hashes','historical_hashes']:
 assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in state[group].items())
missing=[]
for p in list(dest.glob('*.md'))+list((dest/'supporting_docs').glob('*.md')):
 for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not url.startswith(('http:','https:','#','mailto:')) and not (p.parent/url.split('#')[0]).exists():missing.append((str(p.relative_to(dest)),url))
print('Missing local links:',missing)
assert not missing
artifact={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='ARTIFACT_SHA256.json'}
(dest/'ARTIFACT_SHA256.json').write_text(json.dumps(artifact,indent=2)+'\n')
print('Packaged',len(artifact),'files; source snapshot',len(files),'files.')
