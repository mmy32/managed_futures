"""Export the report and its charts as one offline HTML file."""
import base64
import argparse
from html import escape
from pathlib import Path
import re

import markdown
from src.config import QPS_REPORT_DIR



def main(report_name='REPORT.md'):
    report = QPS_REPORT_DIR / report_name
    body = markdown.markdown(report.read_text(), extensions=['tables', 'fenced_code'])
    def inline_image(match):
        path = QPS_REPORT_DIR / match.group(1)
        encoded = base64.b64encode(path.read_bytes()).decode('ascii')
        return f'src="data:image/png;base64,{encoded}"'
    body = re.sub(r'src="([^":]+\.png)"', inline_image, body)
    # Local tables and methods live in the optional code package; no dead links in this file.
    body = re.sub(r'<a href="(?!https?://)([^"]+)">(.+?)</a>', r'<span>\2 (in the code package)</span>', body)
    title = escape(report.read_text().splitlines()[0].lstrip('#').strip())
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>REPORT_TITLE</title><style>
body{max-width:1000px;margin:48px auto;padding:0 24px;font:16px/1.6 system-ui,sans-serif;color:#233044}
h1,h2{line-height:1.2;color:#17395b}h2{margin-top:2em}img{max-width:100%;height:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left}
th{background:#edf3f8}pre{background:#f4f6f8;padding:12px;overflow:auto}a{color:#17648c}
@media print{body{margin:0;font-size:11px}h2{break-after:avoid}img,tr{break-inside:avoid}}
</style><body>'''+body+'</body></html>\n'
    page = page.replace('REPORT_TITLE', title)
    report.with_suffix('.html').write_text(page)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', choices=['REPORT.md', 'ENDPOINT_SENSITIVITY.md'], default='REPORT.md')
    main(parser.parse_args().report)
