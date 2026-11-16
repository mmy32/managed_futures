import numpy as np
import pytest

from src.backtest.cross_validation import cpcv_paths, cpcv_splits, walk_forward_splits


def test_split_counts_match_the_book_example():
    splits = cpcv_splits(n_obs=60, n_groups=6, n_test=2, embargo=0)
    assert len(splits) == 15
    assert len(cpcv_paths(splits, 6)) == 5


def test_each_path_tests_every_group_exactly_once():
    splits = cpcv_splits(120, 8, 2, embargo=3)
    paths = cpcv_paths(splits, 8)
    assert len(paths) == 7
    for path in paths:
        assert sorted(path) == list(range(8))
        assert all(g in splits[i].test_groups for g, i in path.items())
    used = [i for path in paths for i in path.values()]
    assert all(used.count(i) == 2 for i in set(used))


def test_embargo_removes_training_observations_near_test_groups():
    (split,) = [s for s in cpcv_splits(100, 5, 1, embargo=4) if s.test_groups == (2,)]
    assert set(split.test) == set(range(40, 60))
    assert not set(split.train) & set(range(36, 64))
    assert {35, 64, 0, 99} <= set(split.train)


def test_invalid_arguments_raise():
    with pytest.raises(ValueError):
        cpcv_splits(10, 3, 3, 0)
    assert np.array_equal(cpcv_splits(10, 5, 1, 0)[0].test, [0, 1])


def test_walk_forward_training_is_trailing_and_strictly_before_disjoint_tests():
    splits = walk_forward_splits(104, train_months=60, test_months=12, minimum_test_months=8)
    assert len(splits) == 4
    for split in splits:
        assert len(split.train) == 60
        assert split.train[-1] + 1 == split.test[0]
        assert split.train.max() < split.test.min()
        assert not set(split.train) & set(split.test)
    assert [len(split.test) for split in splits] == [12, 12, 12, 8]
    all_tests = np.concatenate([split.test for split in splits])
    assert np.array_equal(all_tests, np.arange(60, 104))
    assert len(walk_forward_splits(103, 60, 12, 8)) == 3


@pytest.mark.parametrize("arguments", [
    (61, 60, 12, 12), (5, 1, 2, 2), (10, 3, 2, 3), (10, 3, 0, 0),
    (10, True, 2, 2), (10.0, 3, 2, 2),
])
def test_walk_forward_rejects_tiny_history_and_invalid_window_sizes(arguments):
    with pytest.raises(ValueError):
        walk_forward_splits(*arguments)
