"""Run the baseline report, or rebuild the complete research pipeline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from src.config import (ASSET_MAP_PATH, CONFIG_DIR, FUTURES_UNDERLYING_DIR, LECTURE_BENCHMARK_PATH,
                        MONTHLY_RETURNS_PATH, PROJECT_ROOT, QPS_OUTPUT_DIR, QPS_REPORT_DIR)

ROOT = PROJECT_ROOT


def run_script(name, allow_data_blocker=False, arguments=()):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *arguments], cwd=ROOT)
    if result.returncode and not (allow_data_blocker and result.returncode == 2):
        result.check_returncode()
    return result.returncode


def validate():
    out = QPS_OUTPUT_DIR / 'risk'
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
    paths = sorted((ROOT / 'scripts').glob('*.py')) + sorted((ROOT / 'src').rglob('*.py'))
    paths += sorted((ROOT / 'tests').rglob('test_*.py')) + sorted(CONFIG_DIR.glob('*.json'))
    record.write_text(json.dumps({
        'verified_utc': datetime.now(timezone.utc).isoformat(),
        'command': 'python scripts/run_research.py --validate',
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
        required = [MONTHLY_RETURNS_PATH, ASSET_MAP_PATH, LECTURE_BENCHMARK_PATH,
                    FUTURES_UNDERLYING_DIR / 'RL.csv', FUTURES_UNDERLYING_DIR / 'ER.csv']
        missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
        if missing:
            parser.error('Missing inputs: ' + ', '.join(missing) + '. See docs/DATA_INPUTS.md.')
    validate()
    if args.validate:
        return
    if args.full:
        run_script('audit_daily.py')
        run_script('review_endpoints.py')
    if args.full or not (QPS_OUTPUT_DIR / 'construction/monthly_returns_research.csv').exists():
        run_script('construct_returns.py')
    if args.full:
        run_script('eda.py')
    if (QPS_OUTPUT_DIR / 'legacy_2000_2014/manifest.json').exists():
        run_script('verify_legacy.py')
    result = run_script('run_risk_research.py', allow_data_blocker=True)
    if result == 0:
        run_script('audit_timing.py')
    if (QPS_REPORT_DIR / 'REPORT.md').exists():
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
