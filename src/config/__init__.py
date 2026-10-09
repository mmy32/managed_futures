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

PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
CLEANING_REPORT_PATH = PROCESSED_DATA_DIR / "cleaning_report.json"

MIN_OBSERVATIONS = 60  # months of data required to keep a market
MAX_ZERO_SHARE = 0.10  # max share of exactly-zero monthly returns
MAX_ABS_RETURN = 1.0  # max |monthly return|; larger is treated as a data error
DUPLICATE_CORRELATION = 0.99  # min correlation to treat two markets as one instrument
DUPLICATE_MIN_OVERLAP = 36  # months both markets must share to compare them

CONFIG_DIR = PROJECT_ROOT / "config"
DOCS_DIR = PROJECT_ROOT / "docs"
LECTURE_BENCHMARK_PATH = RAW_DATA_DIR / "Lecture3_livedata.xlsx"
QPS_REPORT_DIR = PROJECT_ROOT / "reports" / "qps_baseline"
QPS_OUTPUT_DIR = QPS_REPORT_DIR / "output"
