"""Merge duplicate markets into one series per group."""

import pandas as pd


def representative(returns: pd.DataFrame, group: list[str]) -> str:
    """Return the group member with the most observations (ties: first ID)."""
    counts = returns[group].notna().sum()
    return str(counts.sort_values(ascending=False, kind="stable").index[0])


def combine(
    returns: pd.DataFrame, groups: list[list[str]]
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Replace each group by its NaN-aware equal-weighted average return.

    The combined column takes the representative's ID. Returns the new panel and
    the {representative ID: member IDs} mapping.
    """
    combined = returns.drop(columns=[m for g in groups for m in g])
    mapping: dict[str, list[str]] = {}
    series = {}
    for group in groups:
        rep = representative(returns, group)
        mapping[rep] = list(group)
        series[rep] = returns[group].mean(axis=1, skipna=True)
    result = pd.concat([combined, pd.DataFrame(series, index=returns.index)], axis=1)
    return result[sorted(result.columns)], mapping


def combine_prices(
    prices: pd.DataFrame, mapping: dict[str, list[str]]
) -> pd.DataFrame:
    """Combine price columns by averaging daily returns and compounding from 1.0.

    Members missing from the panel are ignored; a group with no members present
    is skipped.
    """
    result = prices.copy()
    for rep, members in mapping.items():
        present = [m for m in members if m in prices.columns]
        if not present:
            continue
        daily = prices[present].pct_change(fill_method=None).mean(axis=1, skipna=True)
        started = prices[present].notna().any(axis=1)
        result = result.drop(columns=present)
        result[rep] = (1 + daily.fillna(0.0)).cumprod().where(started)
    return result[sorted(result.columns)]
