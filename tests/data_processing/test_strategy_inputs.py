import numpy as np
import pandas as pd

from src.data_processing import strategy_inputs


def test_strategy_loader_replaces_retrospective_rl_fallback(tmp_path, monkeypatch):
    months = pd.period_range("2020-01", periods=10, freq="M")
    prices = pd.DataFrame(
        {"RL": 100 + np.arange(10), "ER": 200 + 2 * np.arange(10)},
        index=pd.DatetimeIndex([pd.offsets.BMonthEnd().rollback(d) for d in months.to_timestamp("M")]),
    )
    construction = tmp_path / "construction"
    construction.mkdir()
    research = pd.DataFrame({"A": 0.01, "RL": 0.99}, index=months)
    path = construction / "monthly_returns_research.csv"
    research.to_csv(path)
    monkeypatch.setattr(strategy_inputs, "QPS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(strategy_inputs, "load_daily_prices", lambda: prices)
    settings = {"source_selection": {"minimum_history": 2, "decision_lag_months": 2}}

    original, source, known, _ = strategy_inputs.load_strategy_inputs(settings)
    research.RL = -0.75  # Simulate a different current-month fallback in the archival panel.
    research.to_csv(path)
    changed, other_source, other_known, _ = strategy_inputs.load_strategy_inputs(settings)

    pd.testing.assert_series_equal(original.RL, changed.RL)
    pd.testing.assert_frame_equal(source, other_source)
    pd.testing.assert_series_equal(known, other_known)
    assert source.RL.eq("ER").any()
