"""Export the report and its charts as one offline HTML file."""

import argparse
import base64
import re
from html import escape

import markdown

from src.config import QPS_REPORT_DIR, QPS_VARIANTS


def main(report_name="REPORT.md"):
    report = QPS_REPORT_DIR / report_name
    body = markdown.markdown(report.read_text(), extensions=["tables", "fenced_code", "md_in_html"])

    def inline_image(match):
        path = QPS_REPORT_DIR / match.group(1)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'src="data:image/png;base64,{encoded}"'

    body = re.sub(r'src="([^":]+\.png)"', inline_image, body)
    # Local tables and methods live in the optional code package; no dead links in this file.
    body = re.sub(
        r'<a href="(?!https?://)([^"]+)">(.+?)</a>', r"<span>\2 (in the code package)</span>", body
    )
    title = escape(report.read_text().splitlines()[0].lstrip("#").strip())
    page = (
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>REPORT_TITLE</title><style>
body{max-width:1040px;margin:48px auto;padding:0 28px;font:17px/1.6 system-ui,sans-serif;color:#233044}
h1,h2,h3{line-height:1.25;color:#17395b}h1{font-size:2.1em}h2{margin-top:2.5em;padding-top:1em;border-top:1px solid #dbe3eb;font-size:1.5em}h3{margin-top:1.6em;font-size:1.1em}
p,li{max-width:90ch}li{margin:8px 0}img{display:block;max-width:100%;height:auto;margin:24px auto}
table{border-collapse:collapse;width:100%;font-size:15px;margin:20px 0}th,td{padding:11px 12px;border-bottom:1px solid #dbe3eb;text-align:left;vertical-align:top}
th{background:#edf3f8}tbody tr:nth-child(even){background:#f8fafc}pre{background:#f4f6f8;padding:12px;overflow:auto}a{color:#17648c}
details{margin-top:40px;padding:18px 22px;border:1px solid #dbe3eb;border-radius:8px;background:#f8fafc}summary{cursor:pointer;font-weight:650;color:#17395b}
@media(max-width:640px){body{margin:24px auto;padding:0 16px;font-size:16px}h1{font-size:1.8em}table{display:block;overflow-x:auto;font-size:13px}th,td{padding:8px}}
@media print{body{margin:0;font-size:11px}h2,h3{break-after:avoid}img,tr{break-inside:avoid}details{display:none}}
</style></head><body><main>"""
        + body
        + "</main></body></html>\n"
    )
    page = page.replace("REPORT_TITLE", title)
    report.with_suffix(".html").write_text(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    reports = [name for v in QPS_VARIANTS.values() for name in (v["report"], v["endpoint_report"])]
    parser.add_argument("--report", choices=reports, default="REPORT.md")
    main(parser.parse_args().report)
