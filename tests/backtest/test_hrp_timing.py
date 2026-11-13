"""Point-in-time checks for the complete matched HRP comparison."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.backtest.hrp_comparison import comparison_components, load_comparison
from src.backtest.qps_baseline import forecasts_from
from src.data_processing.endpoints import endpoints
from src.data_processing.strategy_inputs import select_source
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost
from tests.risk_model.test_new_models import daily_frame


def replay(daily, end, lag):
    """Build monthly inputs from daily prices and run both paths without terminal liquidation."""
    months = pd.period_range("1999-12", end, freq="M")
    prices = (1 + daily).cumprod() * 100
    closes = pd.DataFrame(
        {
            market: endpoints(prices[[market]].rename(columns={market: "Close"}), months)
            .endpoint_close
            for market in prices
        }
    )
    returns = closes.pct_change(fill_method=None)
    fallback = returns.RL * 0.8
    fallback.loc[:"2003-12"] = np.nan
    returns["RL"], chosen, schedule = select_source(
        returns.RL, fallback, months, minimum_history=6, decision_lag=2
    )
    source = pd.DataFrame({market: market for market in returns}, index=months)
    source.RL = chosen
    known = pd.Series(pd.to_datetime(schedule.source_known_at).to_numpy(), index=months)
    meta = pd.DataFrame({"AssetClass": ["EQ", "EQ", "FI", "FI"]}, index=returns.columns)
    base = {
        "start": "2003-06", "end": str(end), "signal_months": 12,
        "information_lag_months": lag, "instrument_volatility_scale": 0.4,
        "minimum_instruments": 2, "exclude_from_strategy": {}, "hold_sizing": "hrp_within_class",
    }
    risk = {
        "volatility_months": 36, "volatility_floor_annual": 0.02,
        "correlation_shrinkage": 0.5, "gross_cap": 3, "portfolio_risk_ceiling": 0.1,
        "primary_cost_bps": 2, "primary_band": 0.1,
        "risk_model": {"type": "dcc_garch", "correlation_shrinkage": 0.1,
                       "rescale": {"window": 12, "minimum": 6}},
    }
    spec, _, _ = load_comparison()
    shared, cases = comparison_components(spec, base, risk, returns, meta, source, known, daily)
    sample = returns.loc[shared["start"] : shared["end"]]
    results = {}
    for name, parts in cases.items():
        targets, covariance, _ = forecasts_from(parts, returns, meta, shared)
        details = {}
        ledger, _ = simulate(
            sample, targets["trend"], LinearBpsCost(risk["primary_cost_bps"]),
            source.loc[sample.index], source_known_at=known.loc[sample.index],
            position_policy=BandPolicy(covariance, parts.limits, risk["primary_band"]),
            instrument_details=details, liquidate=False,
        )
        results[name] = (targets["trend"], covariance, details["exposure"], ledger)
    return closes, source, cases["baseline"].risk_model.scale, results


@pytest.mark.parametrize("lag", [1, 2])
def test_hrp_comparison_is_unchanged_by_future_data_and_prefix_replay(lag):
    cutoff = pd.Period("2005-01", freq="M")
    end = pd.Period("2005-06", freq="M")
    daily = daily_frame(["A", "B", "C", "RL"], start="1999-11-01", end="2005-12-31")
    full = replay(daily, end, lag)
    changed = daily.copy()
    changed.loc[cutoff.start_time :] = 0.003 - 0.6 * changed.loc[cutoff.start_time :]
    altered = replay(changed, end, lag)
    prefix = replay(daily.loc[: cutoff.end_time], cutoff, lag)

    # Prices, selected sources, risk rescaling, forecasts, and trades through
    # the cutoff cannot depend on later observations. The cutoff month's own
    # realized return is compared only with the unchanged prefix, not mutation.
    for other in (altered, prefix):
        pd.testing.assert_frame_equal(full[0].loc[: cutoff - 1], other[0].loc[: cutoff - 1])
        pd.testing.assert_frame_equal(full[1].loc[:cutoff], other[1].loc[:cutoff])
        pd.testing.assert_series_equal(full[2].loc[:cutoff], other[2].loc[:cutoff])
        for name in ("baseline", "enhanced"):
            targets, covariance, exposure, ledger = full[3][name]
            other_targets, other_cov, other_exposure, other_ledger = other[3][name]
            pd.testing.assert_frame_equal(targets.loc[:cutoff], other_targets.loc[:cutoff])
            pd.testing.assert_frame_equal(exposure.loc[:cutoff], other_exposure.loc[:cutoff])
            for month in covariance:
                if month <= cutoff:
                    np.testing.assert_allclose(covariance[month], other_cov[month])
            ledger_end = cutoff if other is prefix else cutoff - 1
            pd.testing.assert_frame_equal(ledger.loc[:ledger_end], other_ledger.loc[:ledger_end])
