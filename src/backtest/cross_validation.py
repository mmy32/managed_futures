"""Combinatorial purged cross-validation splits and backtest paths (Lopez de Prado 2018, Ch. 12)."""

from dataclasses import dataclass
from itertools import combinations
from math import comb

import numpy as np


@dataclass(frozen=True)
class Split:
    test_groups: tuple[int, ...]
    test: np.ndarray
    train: np.ndarray


def cpcv_splits(n_obs: int, n_groups: int, n_test: int, embargo: int) -> list[Split]:
    """All train/test splits over `n_groups` contiguous groups with `n_test` groups held out.

    Training observations within `embargo` observations of a test group, before or after, are
    dropped because their estimation windows overlap the test period.
    """
    if not 0 < n_test < n_groups <= n_obs:
        raise ValueError("Need 0 < n_test < n_groups <= n_obs")
    groups = np.array_split(np.arange(n_obs), n_groups)
    splits = []
    for chosen in combinations(range(n_groups), n_test):
        test = np.concatenate([groups[g] for g in chosen])
        banned = np.zeros(n_obs, dtype=bool)
        for g in chosen:
            banned[max(0, groups[g][0] - embargo) : groups[g][-1] + embargo + 1] = True
        splits.append(Split(chosen, test, np.flatnonzero(~banned)))
    return splits


def cpcv_paths(splits: list[Split], n_groups: int) -> list[dict[int, int]]:
    """Backtest paths: each maps a group to the index of the split that tests it on that path."""
    containing = [[i for i, s in enumerate(splits) if g in s.test_groups] for g in range(n_groups)]
    n_paths = comb(n_groups - 1, len(splits[0].test_groups) - 1)
    if any(len(c) != n_paths for c in containing):
        raise ValueError("Splits must cover every group equally often")
    return [{g: containing[g][p] for g in range(n_groups)} for p in range(n_paths)]
