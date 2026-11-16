import numpy as np
import pandas as pd
import pytest
from verify_original_inputs import audit_original_inputs, ohlc_review_flags, reconcile_returns


def test_reconciliation_uses_stored_precision_and_preserves_every_missing_state():
    months = pd.period_range("2000-01", periods=3, freq="M")
    supplied = pd.DataFrame({"A": [0.01, np.nan, 0.0], "B": [0.123456789, 0.02, 0.03]}, index=months)
    tokens = pd.DataFrame({"A": ["0.01", None, "0"],
                           "B": ["0.123456789", "0.02", "0.03"]}, index=months)
    reproduced = supplied.copy()
    reproduced.loc[months[0], "B"] += 4e-10
    before = supplied.copy(deep=True)
    rows, violations = reconcile_returns(supplied, reproduced, tokens)
    assert rows.matching_missingness.all() and rows.all_observed_within_stored_precision.all()
    assert violations.empty
    pd.testing.assert_frame_equal(supplied, before)
    reproduced.loc[months[0], "B"] += 1e-8
    reproduced.loc[months[1], "A"] = 0.0  # Unknown must never silently become zero.
    rows, violations = reconcile_returns(supplied, reproduced, tokens)
    assert rows.missingness_mismatches.sum() == 1 and rows.value_mismatches.sum() == 1
    assert set(violations.issue) == {"missingness_mismatch", "value_outside_stored_precision"}


def test_ohlc_inconsistency_is_a_review_flag_and_never_edits_vendor_data():
    frame = pd.DataFrame({"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [12.0],
                          "Volume": [0], "OpenInterest": [10]}, index=pd.to_datetime(["2012-05-28"]))
    original = frame.copy(deep=True)
    flags = ohlc_review_flags({"ER": frame})
    assert flags.flag.tolist() == ["close_outside_high_low"]
    assert flags.treatment.tolist() == ["review_only_no_changes"]
    pd.testing.assert_frame_equal(frame, original)


def test_existing_verification_directory_is_never_overwritten(tmp_path):
    output = tmp_path / "earlier"
    output.mkdir()
    record = output / "status.json"
    record.write_text("preserved")
    with pytest.raises(ValueError, match="not overwritten"):
        audit_original_inputs(tmp_path / "raw", output)
    assert record.read_text() == "preserved"
