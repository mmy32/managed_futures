"""Clean the monthly, daily and asset-map data consistently."""

from dataclasses import dataclass

import pandas as pd

from src.config import EXCLUDED_MARKETS
from src.data_cleaning.combine import combine, combine_prices
from src.data_cleaning.duplicates import find_duplicate_groups
from src.data_cleaning.quality import exclude, find_low_quality
from src.data_cleaning.report import CleaningReport


@dataclass(frozen=True)
class CleanedData:
    returns: pd.DataFrame
    prices: pd.DataFrame
    asset_map: pd.DataFrame
    report: CleaningReport


def _merge_asset_map(
    asset_map: pd.DataFrame, mapping: dict[str, list[str]]
) -> pd.DataFrame:
    """Keep the representative's row; raise if members disagree on asset class."""
    result = asset_map
    for rep, members in mapping.items():
        present = [m for m in members if m in asset_map.index]
        classes = set(asset_map.loc[present, "AssetClass"])
        if len(classes) > 1:
            raise ValueError(f"group {members} spans asset classes {sorted(classes)}")
        result = result.drop(index=[m for m in present if m != rep])
    return result


def clean(
    returns: pd.DataFrame,
    prices: pd.DataFrame,
    asset_map: pd.DataFrame,
    forced_exclusions: dict[str, str] = EXCLUDED_MARKETS,
) -> CleanedData:
    """Exclude configured and low-quality markets, then merge duplicates, across all inputs.

    Exclusion runs first so bad series cannot contaminate combined ones. Groups and
    exclusions are decided on monthly returns and applied to prices and asset map.
    Forced exclusions are dropped before the quality and duplicate checks.
    """
    forced = {m: why for m, why in forced_exclusions.items() if m in returns.columns}
    low_quality = find_low_quality(exclude(returns, set(forced)))
    excluded = {**forced, **low_quality}
    kept = exclude(returns, set(excluded))
    groups = find_duplicate_groups(kept)
    cleaned_returns, mapping = combine(kept, groups)
    cleaned_prices = combine_prices(exclude(prices, set(excluded)), mapping)
    cleaned_map = _merge_asset_map(asset_map.drop(index=list(excluded), errors="ignore"), mapping)
    return CleanedData(
        cleaned_returns, cleaned_prices, cleaned_map, CleaningReport(excluded, mapping)
    )
