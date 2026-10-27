import numpy as np
import pandas as pd
import pytest

from src.backtest.implementation_diagnostics import (
    activity_summary,
    collateral_rates,
    lagged_activity,
    map_trade_sources,
)
from src.backtest.engine import simulate
from src.backtest.performance import performance
from src.portfolio_construction import BandPolicy
from src.portfolio_construction.limits import PortfolioLimits
from src.transaction_cost_model import LinearBpsCost


def bars():
    dates = pd.to_datetime(["1999-12-28", "1999-12-29", "1999-12-30", "1999-12-31", "2000-01-03"])
    return pd.DataFrame(
        {"Close": [10] * 5, "Volume": [10, 0, 20, 9000, 99999], "OpenInterest": [100] * 5},
        index=dates,
    )


def test_lagged_volume_excludes_latest_bar_and_future_month_and_keeps_zero():
    data = bars()
    months = pd.period_range("2000-01", periods=1, freq="M")
    result = lagged_activity(data, months, 3, 1, 7)
    row = result.iloc[0]
    assert row.mean_reported_volume == 10
    assert row.zero_volume_bars == 1
    assert row.history_through == pd.Timestamp("1999-12-30")
    data.loc["1999-12-31":, "Volume"] = 1e12
    pd.testing.assert_frame_equal(result, lagged_activity(data, months, 3, 1, 7))


def test_short_stale_and_negative_windows_are_flagged_without_filling():
    data = bars().iloc[:3]
    months = pd.PeriodIndex(["2000-01", "2000-03"], freq="M")
    result = lagged_activity(data, months, 3, 1, 7)
    assert result.mean_reported_volume.isna().all()
    assert result.iloc[1].stale
    data.iloc[0, data.columns.get_loc("Volume")] = -1
    assert pd.isna(lagged_activity(data, months, 2, 1, 7).iloc[0].mean_reported_volume)


def test_repeated_bars_are_descriptive_counts():
    data = pd.concat([bars().iloc[:1]] * 5, ignore_index=True)
    data.index = pd.date_range("2000-01-01", periods=5)
    result = activity_summary(data, 5)
    assert result["repeated_full_bars"] == 4
    assert result["rows_in_long_identical_runs"] == 5


def test_source_close_and_open_use_separate_histories():
    months = pd.period_range("2000-01", periods=2, freq="M")
    source = pd.DataFrame({"RL": ["RL", "ER"]}, index=months)
    events = pd.DataFrame(
        dict(
            month=["2000-02"] * 3,
            market=["RL"] * 3,
            event=["source_close", "source_open", "liquidation"],
            timing=["beginning", "beginning", "end"],
        )
    )
    result = map_trade_sources(events, source)
    assert result.source_series.tolist() == ["RL", "ER"]


def test_rf_uses_decimal_monthly_units_and_rejects_missing_or_duplicate_months():
    frame = pd.DataFrame({"Date": ["2000-01-31", "2000-02-29"], "RF": [0.0041, 0.0043]})
    months = pd.period_range("2000-01", periods=2, freq="M")
    np.testing.assert_allclose(collateral_rates(frame, months), [0.0041, 0.0043])
    with pytest.raises(ValueError, match="coverage"):
        collateral_rates(frame, pd.period_range("1999-12", periods=3, freq="M"))
    with pytest.raises(ValueError, match="Duplicate"):
        collateral_rates(pd.concat([frame, frame]), months)


def test_current_collateral_income_cannot_change_current_or_prior_positions():
    months = pd.period_range("2000-01", periods=4, freq="M")
    returns = pd.DataFrame({"A": [0.02, -0.01, 0.03, 0.01]}, index=months)
    targets = returns * 0 + 0.5
    covariance = {month: np.array([[0.001]]) for month in months}
    rates = pd.Series(0.001, index=months)

    def run(cash):
        details = {}
        ledger, _ = simulate(
            returns,
            targets,
            LinearBpsCost(2),
            risk_free=cash,
            position_policy=BandPolicy(covariance, PortfolioLimits(3, 0.1), 0.1),
            instrument_details=details,
        )
        return ledger, details["exposure"]

    original, holdings = run(rates)
    altered = rates.copy()
    altered.iloc[2:] = 0.02
    changed, new_holdings = run(altered)
    pd.testing.assert_frame_equal(original.iloc[:2], changed.iloc[:2])
    pd.testing.assert_frame_equal(holdings.iloc[:3], new_holdings.iloc[:3])
    np.testing.assert_allclose(original.collateral_income, rates * (1 - original.rebalance_cost))
    excess = original.net_return - rates
    assert performance(original, rates)["sharpe"] == pytest.approx(
        excess.mean() / excess.std(ddof=1) * np.sqrt(12)
    )
