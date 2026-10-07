"""Load the market ID to name, currency and asset class map."""

from pathlib import Path

import pandas as pd

from src.config import ASSET_CLASSES, ASSET_MAP_PATH


def load_asset_map(path: Path = ASSET_MAP_PATH) -> pd.DataFrame:
    """Return the asset map indexed by market ID with Name, Ccy and AssetClass.

    Raises ValueError on duplicate IDs or an unknown asset class.
    """
    asset_map = pd.read_csv(path, index_col="ID")
    if not asset_map.index.is_unique:
        duplicated = asset_map.index[asset_map.index.duplicated()].unique().tolist()
        raise ValueError(f"{path}: duplicate market IDs: {duplicated}")
    unknown = set(asset_map["AssetClass"]) - ASSET_CLASSES
    if unknown:
        raise ValueError(f"{path}: unknown asset classes: {sorted(unknown)}")
    return asset_map
