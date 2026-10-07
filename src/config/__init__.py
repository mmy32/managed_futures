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
