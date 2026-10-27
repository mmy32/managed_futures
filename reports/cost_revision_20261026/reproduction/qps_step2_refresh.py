import json,os,subprocess,sys
from pathlib import Path
import pandas as pd
state=json.loads(Path('/private/tmp/qps-cost-revision-state.json').read_text())
stage=Path(state['stage']); sys.path[:0]=[str(stage),str(stage/'scripts')]
from src.config import QPS_OUTPUT_DIR, QPS_REPORT_DIR,CONFIG_DIR
from research_report import write_report
from run_risk_research import write_manifest
from export_report import main as export
from run_research import validate
# Record validation against the final report wording as well as the calculation code.
validate()
settings=json.loads((CONFIG_DIR/'risk_config.json').read_text())
base=json.loads((stage/settings['base_config']).read_text())
for variant,folder,name in [('baseline','endpoint_sensitivity','REPORT.md'),('v2','endpoint_sensitivity_v2','REPORT_V2.md')]:
 out=QPS_OUTPUT_DIR/folder
 read=lambda name:pd.read_csv(out/name)
 write_report(read('comparison.csv'),read('alpha.csv'),read('class_statistics.csv'),read('autocorrelation.csv'),{s:read(f'{s}_class_attribution.csv') for s in ['trend','static']},json.loads((out/'sample_audit.json').read_text()),settings,base,out,QPS_REPORT_DIR/name,json.loads((out/'assumption.json').read_text()),read('stability.csv'),variant)
 write_manifest(settings,base,state['raw_hashes'],out)
 export(name)
 export('ENDPOINT_SENSITIVITY.md' if variant=='baseline' else 'ENDPOINT_SENSITIVITY_V2.md')
print('Final reports and manifests refreshed.')
