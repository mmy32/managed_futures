import numpy as np
import pandas as pd
import pytest

from src.backtest.oos_inputs import strategy_inputs as oos_strategy_inputs
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


@pytest.fixture
def source_prices(tmp_path, monkeypatch):
    dates = pd.bdate_range("2020-01-01", "2022-12-30")
    n = np.arange(len(dates))
    prices = pd.DataFrame({
        "A": 100 * np.exp(0.0004 * n),
        "RL": 75 * np.exp(0.0002 * n),
        "ER": 900 * np.exp(0.0006 * n + 0.002 * np.sin(n)),
    }, index=dates)
    prices.loc["2021-01-01":, "RL"] = np.nan
    months = pd.period_range("2020-01", "2022-12", freq="M")
    construction = tmp_path / "construction"
    construction.mkdir()
    pd.DataFrame({"A": 0.01, "RL": 0.99}, index=months).to_csv(
        construction / "monthly_returns_research.csv"
    )
    monkeypatch.setattr(strategy_inputs, "QPS_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(strategy_inputs, "load_daily_prices", lambda: prices)
    settings = {"source_selection": {"minimum_history": 2, "decision_lag_months": 2}}
    return prices, settings


def test_daily_risk_source_survives_original_contract_end_and_matches_oos(source_prices):
    prices, settings = source_prices
    monthly, source, _, _ = strategy_inputs.load_strategy_inputs(settings)
    historical = strategy_inputs.load_daily_returns(["A", "RL"], settings)
    oos_monthly, oos_source, _, daily = oos_strategy_inputs(
        prices, ["A", "RL"], settings, monthly.index[-1]
    )
    pd.testing.assert_series_equal(monthly.RL, oos_monthly.RL)
    pd.testing.assert_frame_equal(source, oos_source)
    pd.testing.assert_frame_equal(historical, daily)
    assert historical.loc["2021-01-01":, "RL"].notna().all()
    assert monthly.loc["2021-01":, "RL"].notna().all()
    er = prices.ER / prices.ER.shift(1) - 1
    pd.testing.assert_series_equal(historical.loc["2021-01-01":, "RL"],
                                   er.loc["2021-01-01":], check_names=False)
    # Distinct price levels ensure a cross-contract ratio would fail this check.
    selected = source.RL.eq("ER")
    first_er = source.index[selected][0].start_time
    np.testing.assert_allclose(historical.loc[first_er:, "RL"], er.loc[first_er:])


def test_daily_risk_source_is_unchanged_by_future_prices(source_prices, monkeypatch):
    prices, settings = source_prices
    original = strategy_inputs.load_daily_returns(["A", "RL"], settings)
    _, original_source, _, _ = strategy_inputs.load_strategy_inputs(settings)
    changed = prices.copy()
    changed.loc["2022-01-01":, "ER"] *= 1.7
    monkeypatch.setattr(strategy_inputs, "load_daily_prices", lambda: changed)
    altered = strategy_inputs.load_daily_returns(["A", "RL"], settings)
    _, altered_source, _, _ = strategy_inputs.load_strategy_inputs(settings)
    pd.testing.assert_frame_equal(original.loc[:"2021-12-31"], altered.loc[:"2021-12-31"])
    pd.testing.assert_frame_equal(original_source.loc[:"2021-12"],
                                  altered_source.loc[:"2021-12"])
    assert not original.loc["2022-01-01":].equals(altered.loc["2022-01-01":])


def test_daily_risk_returns_reject_an_unknown_source_schedule(source_prices):
    prices, _ = source_prices
    source = pd.DataFrame({"RL": ["ER"]}, index=pd.period_range("2022-12", periods=1, freq="M"))
    with pytest.raises(ValueError, match="complete RL/ER source schedule"):
        strategy_inputs.source_consistent_daily_returns(prices, source)


@pytest.mark.parametrize("declare_excluded", [True, False])
def test_excluded_or_unused_only_dates_cannot_change_daily_risk_grid(monkeypatch, declare_excluded):
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08", "2024-01-09"])
    retained = pd.DataFrame({"A": [100, 101, np.nan, 103, 104],
                             "B": [200, 202, 204, 206, 208]}, index=dates)
    monkeypatch.setattr(strategy_inputs, "load_daily_prices", lambda: retained)
    expected = strategy_inputs.load_daily_returns(["A", "B"])
    added_dates = pd.to_datetime(["2024-01-04", "2024-01-06"])
    augmented = retained.reindex(retained.index.union(added_dates))
    augmented["EC"] = np.nan
    augmented.loc[added_dates, "EC"] = [999, 2]
    monkeypatch.setattr(strategy_inputs, "load_daily_prices", lambda: augmented)
    markets = ["A", "B", "EC"] if declare_excluded else ["A", "B"]
    actual = strategy_inputs.load_daily_returns(markets, excluded=["EC"])
    pd.testing.assert_frame_equal(actual, expected)
    assert added_dates.intersection(actual.index).empty
    # A real gap remains because B has an observation on that date. Its first
    # following ratio is also unknown, rather than an invented daily return.
    assert actual.loc["2024-01-05":"2024-01-08", "A"].isna().all()
    assert actual.loc["2024-01-09", "A"] == pytest.approx(104 / 103 - 1)
    monthly, _, _, oos_daily = oos_strategy_inputs(
        augmented, markets, {}, pd.Period("2024-01", freq="M"), excluded=["EC"]
    )
    assert monthly.columns.tolist() == markets
    pd.testing.assert_frame_equal(oos_daily, expected)
