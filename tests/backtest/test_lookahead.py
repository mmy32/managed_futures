"""Causal checks from source selection through actual trades and portfolio P&L."""

import copy

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.data_processing.strategy_inputs import select_source
from src.risk_model.risk_model import BandPolicy, build_forecasts


def setup():
    rng = np.random.default_rng(862)
    idx = pd.period_range("1995-01", periods=100, freq="M")
    r = pd.DataFrame(rng.normal(0.003, 0.02, (100, 4)), index=idx, columns=["A", "B", "C", "RL"])
    fallback = pd.Series(rng.normal(0.003, 0.02, 100), index=idx)
    fallback.loc[:"1998-06"] = np.nan
    meta = pd.DataFrame({"AssetClass": ["EQ", "FI", "FX", "EQ"]}, index=r.columns)
    base = {
        "start": "2000-01",
        "end": "2003-04",
        "signal_months": 12,
        "volatility_months": 36,
        "information_lag_months": 1,
        "volatility_floor_annual": 0.02,
        "instrument_volatility_scale": 0.4,
        "minimum_instruments": 2,
        "exclude_from_strategy": {},
    }
    cfg = {
        "volatility_months": 36,
        "volatility_floor_annual": 0.02,
        "portfolio_risk_ceiling": 0.1,
        "gross_cap": 3,
        "correlation_shrinkage": 0.5,
    }
    return r, fallback, meta, base, cfg


def pipeline(raw, fallback, meta, base, cfg, model="correlated", band=0.1):
    r = raw.copy()
    r["RL"], chosen, schedule = select_source(r.RL, fallback, r.index, 36, 2)
    source = pd.DataFrame({a: a for a in r}, index=r.index)
    source.RL = chosen
    known = pd.Series(pd.to_datetime(schedule.source_known_at).to_numpy(), index=r.index)
    targets, cov, _ = build_forecasts(r, meta, base, cfg, model)
    sample = r.loc[base["start"] : base["end"]]
    policy = BandPolicy(cov, cfg, band)
    ledger, _ = simulate(
        sample,
        targets["trend"],
        5,
        source.loc[sample.index],
        liquidate=False,
        position_policy=policy,
        source_known_at=known.loc[sample.index],
    )
    executed = pd.DataFrame.from_dict(policy.executed, orient="index", columns=r.columns)
    return ledger, executed, targets["trend"], cov, source


@pytest.mark.parametrize("model", ["diagonal", "correlated", "class_balanced"])
@pytest.mark.parametrize("band", [0, 0.1, 0.2])
def test_future_return_perturbation_preserves_complete_past_trading_path(model, band):
    r, f, m, b, c = setup()
    cutoff = pd.Period("2001-07", "M")
    original = pipeline(r, f, m, b, c, model, band)
    modified = r.copy()
    modified.loc[cutoff:] = -0.7 * modified.loc[cutoff:] + 0.012
    f2 = f.copy()
    f2.loc[cutoff:] = -0.6 * f2.loc[cutoff:] + 0.01
    altered = pipeline(modified, f2, m, b, c, model, band)
    pd.testing.assert_frame_equal(original[1].loc[:cutoff], altered[1].loc[:cutoff])
    pd.testing.assert_frame_equal(original[2].loc[:cutoff], altered[2].loc[:cutoff])
    pd.testing.assert_frame_equal(original[0].loc[: cutoff - 1], altered[0].loc[: cutoff - 1])
    pd.testing.assert_frame_equal(original[4].loc[:cutoff], altered[4].loc[:cutoff])
    for t in original[3]:
        if t <= cutoff:
            np.testing.assert_allclose(original[3][t], altered[3][t])


@pytest.mark.parametrize("cutoff", ["2000-05", "2001-09", "2002-10"])
def test_truncated_history_replay_matches_full_run(cutoff):
    r, f, m, b, c = setup()
    cutoff = pd.Period(cutoff, "M")
    full = pipeline(r, f, m, b, c)
    shortened = copy.deepcopy(b)
    shortened["end"] = str(cutoff)
    prefix = pipeline(r.loc[:cutoff], f.loc[:cutoff], m, shortened, c)
    pd.testing.assert_frame_equal(full[0].loc[:cutoff], prefix[0])
    pd.testing.assert_frame_equal(full[1].loc[:cutoff], prefix[1])


def test_realized_source_availability_cannot_select_current_source():
    r, f, _m, _b, _c = setup()
    _selected, source, schedule = select_source(r.RL, f, r.index, 36, 2)
    month = source.index[source.eq("ER")][0]
    broken = f.copy()
    broken.loc[month] = np.nan
    changed, changed_source, _ = select_source(r.RL, broken, r.index, 36, 2)
    assert changed_source.loc[month] == "ER"
    assert pd.isna(changed.loc[month])  # Must fail held-P&L validation, not rescue with RL.
    assert source.loc[month - 1] == "RL"
    assert schedule.loc[schedule.month.eq(month), "information_through"].iloc[0] == month - 2


def test_policy_cannot_receive_unstamped_or_future_source_information():
    idx = pd.period_range("2000-01", periods=2, freq="M")
    r = pd.DataFrame([0.01, 0.02], index=idx, columns=["A"])
    targets = r * 0 + 0.1
    source = pd.DataFrame("A", index=idx, columns=r.columns)
    cov = {t: np.array([[0.01]]) for t in idx}
    cfg = setup()[-1]
    with pytest.raises(ValueError, match="source_known_at"):
        simulate(r, targets, 5, source, position_policy=BandPolicy(cov, cfg, 0.1))
    with pytest.raises(ValueError, match="known before"):
        simulate(
            r,
            targets,
            5,
            source,
            position_policy=BandPolicy(cov, cfg, 0.1),
            source_known_at=pd.Series(idx.to_timestamp(), index=idx),
        )


def test_calendar_holes_and_zero_lag_are_rejected():
    r, _f, m, b, c = setup()
    with pytest.raises(ValueError, match="complete monthly calendar"):
        build_forecasts(r.drop(r.index[60]), m, b, c)
    b["information_lag_months"] = 0
    with pytest.raises(ValueError, match="information lag"):
        build_forecasts(r, m, b, c)
