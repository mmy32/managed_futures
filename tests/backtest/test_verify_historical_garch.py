"""Historical diagnostics must preserve unknowns and withhold success on missing inputs."""

import pandas as pd
import pytest
from verify_garch_fixes import EXCLUDED, MARKETS, SEED, synthetic_prices
from verify_historical_garch import prepare, run_verification, unknown_return_mask


def test_historical_preparation_preserves_monthly_missing_cells_and_end_boundary():
    prices = synthetic_prices(SEED)
    months = pd.period_range("1999-11", "2002-03", freq="M")
    supplied = pd.DataFrame(0.01, index=months, columns=MARKETS)
    supplied.loc["2000-08", "EQ1"] = float("nan")
    original = supplied.copy()
    end = pd.Period("2001-12", freq="M")
    base = {"exclude_from_strategy": EXCLUDED}
    risk = {"source_selection": {"minimum_history": 6, "decision_lag_months": 2}}
    returns, _, _, daily = prepare(prices, supplied, base, risk, end)
    assert returns.index[-1] == end
    assert daily.index[-1] <= end.end_time
    pd.testing.assert_frame_equal(returns.drop(columns="RL"),
                                  original.loc[:end].drop(columns="RL"))
    pd.testing.assert_frame_equal(supplied, original)


def test_unknown_intervals_follow_selected_er_not_terminated_rl():
    dates = pd.bdate_range("2013-01-02", periods=3)
    prices = pd.DataFrame({"RL": [float("nan")]*3, "ER": [100.0, 101.0, 102.0]}, index=dates)
    source = pd.DataFrame({"RL": ["ER"]}, index=pd.PeriodIndex(["2013-01"], freq="M"))
    daily = pd.DataFrame({"RL": [float("nan"), 0.01, 102/101-1]}, index=dates)
    mask = unknown_return_mask(prices, source, daily)
    assert mask.RL.tolist() == [True, False, False]


def test_missing_historical_inputs_produce_readable_failed_record(tmp_path):
    output = tmp_path / "verification"
    assert not run_verification(output, tmp_path / "absent-raw-inputs")
    checks = pd.read_csv(output / "checks.csv")
    assert not checks.passed.all()
    assert "**FAIL" in (output / "SUMMARY.md").read_text()
    assert (output / "manifest.json").is_file()


def test_historical_verification_never_overwrites_existing_record(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(FileExistsError):
        run_verification(tmp_path)
    assert marker.read_text() == "preserve"
