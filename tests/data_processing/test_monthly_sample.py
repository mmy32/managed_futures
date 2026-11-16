"""Availability-conditioned samples must be explicit and cannot alter raw returns."""

import numpy as np
import pandas as pd
import pytest

from src.data_processing.monthly_sample import (
    COVERAGE_SELECTION_NOTE,
    audit_monthly_universe,
)


def monthly_panel():
    return pd.DataFrame(
        {
            "leading": [np.nan, 0.01, 0.02, 0.03, 0.04, 0.05],
            "internal": [0.01, np.nan, 0.02, 0.03, 0.04, 0.05],
            "terminal": [0.01, 0.02, 0.03, 0.04, np.nan, np.nan],
            "excluded": [0.01] * 6,
        },
        index=pd.period_range("2014-11", "2015-04", freq="M"),
    )


def test_leading_blanks_allowed_but_internal_and_terminal_gaps_excluded():
    returns = monthly_panel()
    original = returns.copy(deep=True)
    audit = audit_monthly_universe(returns, {"excluded": "Fixed identity policy"}, "2015-04")
    assert audit.included_coverage.to_dict() == {
        "leading": True, "internal": False, "terminal": False, "excluded": False,
    }
    assert audit.loc["leading", "first_observed"] == "2014-12"
    assert audit.loc["internal", "missing_internal"] == 1
    assert audit.loc["internal", "missing_post_2014"] == 0
    assert audit.loc["terminal", "missing_internal"] == 0
    assert audit.loc["terminal", "missing_after_first"] == 2
    assert audit.loc["terminal", "missing_post_2014"] == 2
    assert "Predeclared" in audit.loc["excluded", "exclusion_reason"]
    pd.testing.assert_frame_equal(returns, original)


def test_full_sample_availability_changes_selection_but_return_values_do_not():
    returns = monthly_panel()
    before = audit_monthly_universe(returns, (), "2015-02")
    full = audit_monthly_universe(returns, (), "2015-04")
    assert before.loc["terminal", "included_coverage"]
    assert not full.loc["terminal", "included_coverage"]
    changed = returns * -37.0
    pd.testing.assert_frame_equal(full, audit_monthly_universe(changed, (), "2015-04"))
    assert "retrospective" in COVERAGE_SELECTION_NOTE
    assert "not an ex-ante universe" in COVERAGE_SELECTION_NOTE


def test_observations_after_declared_end_do_not_affect_audit():
    returns = monthly_panel()
    prefix = audit_monthly_universe(returns, (), "2015-02")
    returns.loc["2015-03":, "leading"] = np.nan
    pd.testing.assert_frame_equal(prefix, audit_monthly_universe(returns, (), "2015-02"))


@pytest.mark.parametrize("defect", ["empty", "duplicate_markets", "gap", "infinite", "unobserved"])
def test_invalid_monthly_inputs_fail_fast(defect):
    returns = monthly_panel()
    if defect == "empty":
        returns = returns.iloc[:0]
    elif defect == "duplicate_markets":
        returns.columns = ["same"] * len(returns.columns)
    elif defect == "gap":
        returns = returns.drop(returns.index[2])
    elif defect == "infinite":
        returns.iloc[0, 0] = np.inf
    else:
        returns["unobserved"] = np.nan
    with pytest.raises(ValueError):
        audit_monthly_universe(returns, (), "2015-04")


def test_sample_end_and_exclusions_must_match_supplied_panel():
    with pytest.raises(ValueError, match="sample end"):
        audit_monthly_universe(monthly_panel(), (), "2025-05")
    with pytest.raises(ValueError, match="exclusions"):
        audit_monthly_universe(monthly_panel(), {"typo": "Unknown"}, "2015-04")
