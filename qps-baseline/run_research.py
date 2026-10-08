"""Run the baseline report, or rebuild the complete research pipeline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent


def run_script(name, allow_data_blocker=False, arguments=()):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *arguments], cwd=ROOT)
    if result.returncode and not (allow_data_blocker and result.returncode == 2):
        result.check_returncode()
    return result.returncode


def validate():
    out = ROOT / 'output/risk'
    out.mkdir(parents=True, exist_ok=True)
    record = out / 'validation.json'
    record.unlink(missing_ok=True)
    xml = out / 'pytest-results.xml'
    subprocess.run([sys.executable, '-m', 'pytest', '-q', f'--junitxml={xml}'], cwd=ROOT, check=True)
    suites = ET.parse(xml).getroot().iter('testsuite')
    totals = {k: 0 for k in ['tests', 'failures', 'errors', 'skipped']}
    for suite in suites:
        for k in totals:
            totals[k] += int(suite.get(k, 0))
    paths = sorted((ROOT / 'scripts').glob('*.py')) + sorted((ROOT / 'tests').glob('*.py'))
    paths += [ROOT / 'run_research.py', ROOT / 'pytest.ini']
    paths += sorted((ROOT / 'config').glob('*.json'))
    record.write_text(json.dumps({
        'verified_utc': datetime.now(timezone.utc).isoformat(),
        'command': 'python run_research.py --validate',
        'passed': totals['tests'] - totals['failures'] - totals['errors'] - totals['skipped'],
        'failed': totals['failures'] + totals['errors'],
        'skipped': totals['skipped'],
        'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    }, indent=2) + '\n')
    xml.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument('--full', action='store_true', help='Rebuild daily audit, endpoint review, monthly data, EDA and baseline report')
    options.add_argument('--validate', action='store_true', help='Run tests only; no source data required')
    parser.add_argument('--endpoint-sensitivity', action='store_true',
                        help='Also evaluate a separate, unverified March 1997 endpoint assumption')
    args = parser.parse_args()
    if not args.validate:
        required = ['MonthlyReturns.csv', 'AssetMapCsv.csv', 'Lecture3_livedata.xlsx',
                    'FuturesUnderlyingData/RL.csv', 'FuturesUnderlyingData/ER.csv']
        missing = [name for name in required if not (ROOT / 'data' / name).is_file()]
        if missing:
            parser.error('Missing inputs: ' + ', '.join(missing) + '. See data/README.md.')
    validate()
    if args.validate:
        return
    if args.full:
        run_script('audit_daily.py')
        run_script('review_endpoints.py')
    if args.full or not (ROOT / 'output/construction/monthly_returns_research.csv').exists():
        run_script('construct_returns.py')
    if args.full:
        run_script('eda.py')
    if (ROOT / 'output/legacy_2000_2014/manifest.json').exists():
        run_script('verify_legacy.py')
    result = run_script('run_risk_research.py', allow_data_blocker=True)
    if result == 0:
        run_script('audit_timing.py')
    if (ROOT/'REPORT.md').exists():
        run_script('export_report.py')
    if args.endpoint_sensitivity:
        run_script('run_risk_research.py', arguments=['--endpoint-sensitivity'])
        run_script('export_report.py')
        run_script('export_report.py', arguments=['--report', 'ENDPOINT_SENSITIVITY.md'])
        print('Presentation ready: REPORT.md and REPORT.html; ENDPOINT_SENSITIVITY remains a compatible copy. Preserved-policy status: docs/DATA_STATUS.md.')
        return 0
    if result == 2:
        print('Data blocked: docs/DATA_STATUS.md explains the missing held returns. Run --endpoint-sensitivity to refresh the conditional presentation report.')
        return 2
    print('Ready: REPORT.md (GitHub) and REPORT.html (standalone, with embedded charts).')


if __name__ == '__main__':
    raise SystemExit(main())
