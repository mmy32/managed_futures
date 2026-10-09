"""Find groups of markets that are the same instrument."""

import pandas as pd

from src.config import DUPLICATE_CORRELATION, DUPLICATE_MIN_OVERLAP


def find_duplicate_groups(
    returns: pd.DataFrame,
    min_correlation: float = DUPLICATE_CORRELATION,
    min_overlap: int = DUPLICATE_MIN_OVERLAP,
) -> list[list[str]]:
    """Return groups (sorted ID lists, size >= 2) linked by high return correlation.

    Two markets are linked when they share at least `min_overlap` months and their
    correlation over those months is at least `min_correlation`. Groups are the
    connected components of the links.
    """
    corr = returns.corr(min_periods=min_overlap)
    parent = {m: m for m in returns.columns}

    def root(m: str) -> str:
        while parent[m] != m:
            parent[m] = parent[parent[m]]
            m = parent[m]
        return m

    for i, a in enumerate(returns.columns):
        for b in returns.columns[i + 1 :]:
            if corr.loc[a, b] >= min_correlation:
                parent[root(b)] = root(a)

    members: dict[str, list[str]] = {}
    for m in returns.columns:
        members.setdefault(root(m), []).append(m)
    return sorted(sorted(g) for g in members.values() if len(g) > 1)
