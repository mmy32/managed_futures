"""Project-wide settings: data locations and file-format constants."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
MONTHLY_RETURNS_PATH = RAW_DATA_DIR / "MonthlyReturns.csv"
ASSET_MAP_PATH = RAW_DATA_DIR / "AssetMapCsv.csv"
FUTURES_UNDERLYING_DIR = RAW_DATA_DIR / "futures_underlying"

MONTHLY_DATE_FORMAT = "%m/%d/%Y"
ASSET_CLASSES = frozenset({"COMM", "EQ", "FI", "FX"})
PRICE_COLUMN = "Close"
DAILY_BAR_FIELDS = ["Open", "High", "Low", "Close", "Volume", "OpenInterest"]

PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
CLEANING_REPORT_PATH = PROCESSED_DATA_DIR / "cleaning_report.json"

MIN_OBSERVATIONS = 60  # months of data required to keep a market
MAX_ZERO_SHARE = 0.10  # max share of exactly-zero monthly returns
MAX_ABS_RETURN = 1.0  # max |monthly return|; larger is treated as a data error
DUPLICATE_CORRELATION = 0.99  # min correlation to treat two markets as one instrument
DUPLICATE_MIN_OVERLAP = 36  # months both markets must share to compare them
EXCLUDED_MARKETS = {  # market ID -> reason; dropped before quality checks and duplicate merging
    "YM": "Duplicate Dow exposure; retain older ZD series.",
    "EC": "Instrument identity/classification unresolved; omit rather than assign an unverified class.",
}

CONFIG_DIR = PROJECT_ROOT / "config"
DOCS_DIR = PROJECT_ROOT / "docs"
LECTURE_BENCHMARK_PATH = RAW_DATA_DIR / "Lecture3_livedata.xlsx"
QPS_REPORT_DIR = PROJECT_ROOT / "reports" / "qps_baseline"
QPS_OUTPUT_DIR = QPS_REPORT_DIR / "output"

MONTHS_PER_YEAR = 12
EWMA_CENTER_OF_MASS_DAYS = 60  # Moskowitz-Ooi-Pedersen (2012) Eq. 1
EWMA_TRADING_DAYS_PER_YEAR = 261  # annualization used in the same equation
EWMA_MIN_OBSERVATIONS = 60  # daily returns required before an EWMA volatility is used

TSMOM_REPORT_DIR = PROJECT_ROOT / "reports" / "tsmom_baseline"

# qps strategy variants: where each writes. "v2" chooses the trend signal per asset class.
QPS_VARIANTS = {
    "baseline": {
        "output": "risk",
        "endpoint_output": "endpoint_sensitivity",
        "report": "REPORT.md",
        "endpoint_report": "ENDPOINT_SENSITIVITY.md",
        "status": "DATA_STATUS.md",
    },
    "v2": {
        "output": "risk_v2",
        "endpoint_output": "endpoint_sensitivity_v2",
        "report": "REPORT_V2.md",
        "endpoint_report": "ENDPOINT_SENSITIVITY_V2.md",
        "status": "DATA_STATUS_V2.md",
    },
}
DEFAULT_QPS_VARIANT = "v2"
