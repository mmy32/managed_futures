"""Chronological selection splits and optional historical combinatorial diagnostics."""

from dataclasses import dataclass
from itertools import combinations
from math import comb

import numpy as np


@dataclass(frozen=True)
class Split:
    test_groups: tuple[int, ...]
    test: np.ndarray
    train: np.ndarray


@dataclass(frozen=True)
class WalkForwardSplit:
    train: np.ndarray
    test: np.ndarray


def walk_forward_splits(
    n_obs: int, train_months: int, test_months: int, minimum_test_months: int
) -> list[WalkForwardSplit]:
    """Trailing training windows followed by disjoint, strictly later test windows.

    A final partial window is retained only when its declared minimum is met.
    These indices define selection diagnostics; joining separately maintained
    candidate ledgers does not create an executable switching portfolio.
    """
    values = (n_obs, train_months, test_months, minimum_test_months)
    if any(type(value) is not int for value in values):
        raise ValueError("Walk-forward sizes must be integers")
    if train_months < 2 or not 2 <= minimum_test_months <= test_months:
        raise ValueError("Need at least two training/test months and minimum <= test window")
    if n_obs < train_months + minimum_test_months:
        raise ValueError("Insufficient history for a training window and test minimum")
    splits = []
    for start in range(train_months, n_obs, test_months):
        stop = min(start + test_months, n_obs)
        if stop - start < minimum_test_months:
            break
        splits.append(WalkForwardSplit(np.arange(start - train_months, start),
                                       np.arange(start, stop)))
    return splits


def cpcv_splits(n_obs: int, n_groups: int, n_test: int, embargo: int) -> list[Split]:
    """All train/test splits over `n_groups` contiguous groups with `n_test` groups held out.

    Training observations near test groups are dropped. Training may still be
    later than testing, and a finite embargo does not isolate an expanding-fit
    model or an arbitrarily long calibration state. This is a historical
    sensitivity diagnostic, not an independent chronological assessment.
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
