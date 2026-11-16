import numpy as np
import pandas as pd
import pytest

from src.data_processing.input_audit import (
    market_coverage,
    missing_runs,
    reconcile_monthly,
)


def test_overlap_respects_stored_precision_and_separates_added_changed_removed():
    index = pd.period_range("2014-01", periods=4, freq="M")
    old = pd.DataFrame({"A": [0.123, np.nan, 0.02, 0.03]}, index=index)
    tokens = pd.DataFrame({"A": ["0.123", np.nan, "0.02", "0.03"]}, index=index)
    full = pd.DataFrame({"A": [0.1234, 0.04, 0.04, np.nan]}, index=index)
    summary, changes = reconcile_monthly(old, full, tokens)
    assert summary["observed_changes_beyond_precision"] == 1
    assert summary["added_observations"] == 1
    assert summary["removed_observations"] == 1
    assert changes.change.tolist() == ["added", "changed_beyond_stored_precision", "removed"]
    assert np.isnan(old.iloc[1, 0])


def test_coverage_does_not_call_pre_inception_blanks_internal_gaps():
    index = pd.period_range("2014-01", periods=6, freq="M")
    panel = pd.DataFrame({"A": [np.nan, 0.01, np.nan, 0.02, np.nan, np.nan]}, index=index)
    meta = pd.DataFrame({"AssetClass": ["EQ"]}, index=["A"])
    row = market_coverage(panel, meta, index[2]).iloc[0]
    assert row.interior_missing_months == 1
    assert row.missing_months == 4
    assert row.post_development_missing == 2
    runs = missing_runs(panel, index[2])
    assert runs.missing_months.tolist() == [1, 2]
    assert runs.resumption_month.tolist() == ["2014-04", ""]


def test_overlap_rejects_silent_market_reordering():
    index = pd.period_range("2014-01", periods=2, freq="M")
    panel = pd.DataFrame({"A": 0.01, "B": 0.02}, index=index)
    with pytest.raises(ValueError, match="identical market"):
        reconcile_monthly(panel, panel[["B", "A"]], panel.astype(str))


def test_overlap_allows_excel_representation_noise_and_reports_lost_whole_month():
    index = pd.period_range("2014-01", periods=2, freq="M")
    panel = pd.DataFrame({"A": [0.16279069767441867, 0.02]}, index=index)
    tokens = pd.DataFrame({"A": ["0.16279069767441867", "0.02"]}, index=index)
    expanded = pd.DataFrame({"A": [0.162790697674418]}, index=index[:1])
    summary, changes = reconcile_monthly(panel, expanded, tokens)
    assert summary["observed_changes_beyond_precision"] == 0
    assert summary["original_only_observed_cells"] == 1
    assert changes.empty
