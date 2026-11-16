"""Fast checks of the exported numerical evidence and failure-probe isolation."""

import pandas as pd
import pytest
from verify_garch_fixes import (
    SEED,
    moment_checks,
    optimizer_checks,
    run_verification,
    source_checks,
    synthetic_prices,
    variance_checks,
)

from src.risk_model import garch


def test_missing_observation_exports_show_corrected_and_counterfactual_states(tmp_path):
    results = variance_checks(tmp_path) + moment_checks(tmp_path)
    assert all(row["passed"] for row in results)
    variance = pd.read_csv(tmp_path / "variance_trace.csv")
    gap_state = variance.iloc[3]
    assert gap_state.fixed_calendar_variance > gap_state.zero_imputation_counterfactual
    assert gap_state.fixed_calendar_variance < gap_state.compressed_time_counterfactual
    state = pd.read_csv(tmp_path / "dcc_missing_state_trace.csv").iloc[-1]
    assert state.fixed_q_diagonal == pytest.approx(1.0)
    assert state.zero_shock_counterfactual_diagonal == pytest.approx(0.6, abs=1e-5)


def test_failed_estimation_probe_restores_real_optimizer():
    original = garch.minimize
    results = optimizer_checks(synthetic_prices(SEED), SEED)
    assert all(row["passed"] for row in results)
    assert garch.minimize is original


def test_source_evidence_contains_er_returns_after_rl_disappears(tmp_path):
    assert source_checks(tmp_path, synthetic_prices(SEED))[0]["passed"]
    source = pd.read_csv(tmp_path / "source_continuation.csv")
    assert source.raw_RL_return.isna().all()
    assert source.selected_daily_risk_return.notna().all()
    pd.testing.assert_series_equal(source.selected_daily_risk_return,
                                   source.ER_own_daily_return, check_names=False)


def test_verification_refuses_to_overwrite_existing_directory(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(FileExistsError):
        run_verification(tmp_path)
    assert marker.read_text() == "preserve"
