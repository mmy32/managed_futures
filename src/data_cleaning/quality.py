"""Flag low-quality markets and drop them."""

import pandas as pd

from src.config import MAX_ABS_RETURN, MAX_ZERO_SHARE, MIN_OBSERVATIONS


def find_low_quality(
    returns: pd.DataFrame,
    min_observations: int = MIN_OBSERVATIONS,
    max_zero_share: float = MAX_ZERO_SHARE,
    max_abs_return: float = MAX_ABS_RETURN,
) -> dict[str, str]:
    """Return {market ID: reason} for markets that fail a quality threshold."""
    counts = returns.notna().sum()
    zero_share = (returns == 0).sum() / counts.where(counts > 0)
    largest = returns.abs().max()
    flagged: dict[str, str] = {}
    for market in returns.columns:
        if counts[market] < min_observations:
            flagged[market] = f"{counts[market]} observations < {min_observations}"
        elif zero_share[market] > max_zero_share:
            flagged[market] = f"zero-return share {zero_share[market]:.3f} > {max_zero_share}"
        elif largest[market] > max_abs_return:
            flagged[market] = f"|return| {largest[market]:.3f} > {max_abs_return}"
    return flagged


def exclude(panel: pd.DataFrame, market_ids: set[str]) -> pd.DataFrame:
    """Return the panel without the given markets; IDs absent from it are ignored."""
    return panel.drop(columns=[m for m in panel.columns if m in market_ids])
