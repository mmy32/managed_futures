"""The paper-style baseline must not select its history using future observations."""

import json

import numpy as np
import pandas as pd
import pytest
from run_tsmom_baseline import main, market_data_from_prices, run

from src.config import CONFIG_DIR
from src.models import MarketData


def inputs():
    config = json.loads((CONFIG_DIR / "tsmom_baseline.json").read_text())
    config.update(
        history_start="2018-01", start="2020-01", end="2022-12",
        universe=["A", "B", "EXCLUDED"], exclude_from_strategy={"EXCLUDED": "fixed policy"},
    )
    dates = pd.bdate_range("2018-01-01", "2022-12-30")
    rng = np.random.default_rng(728)
    returns = rng.normal(0.001, 0.004, (len(dates), 3))
    prices = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=dates,
                          columns=config["universe"])
    meta = pd.DataFrame({"AssetClass": ["EQ", "FI", "FX"]}, index=prices.columns)
    return prices, meta, config


def test_future_extremes_availability_and_new_columns_cannot_select_past_universe_or_trades():
    prices, meta, config = inputs()
    changed = prices.copy()
    changed.loc["2021":, "A"] = np.nan
    changed.loc["2021":, "B"] *= 1e8
    changed["FUTURE"] = np.where(changed.index.year >= 2021, 100.0, np.nan)
    changed["EXCLUDED"] = 0.0
    first = market_data_from_prices(prices, meta, config)
    second = market_data_from_prices(changed, meta, config)
    assert list(first.returns) == list(second.returns) == ["A", "B"]
    pd.testing.assert_frame_equal(first.returns.loc[:"2020"], second.returns.loc[:"2020"])
    pd.testing.assert_frame_equal(first.meta, second.meta)
    simulation = {**config, "end": "2020-12"}
    before, after = {}, {}
    first_ledger, first_pnl = run(first, simulation, before)
    second_ledger, second_pnl = run(second, simulation, after)
    pd.testing.assert_frame_equal(before["exposure"], after["exposure"])
    pd.testing.assert_frame_equal(first_ledger, second_ledger)
    pd.testing.assert_frame_equal(first_pnl, second_pnl)
    assert first_ledger.held_instruments.gt(0).all()


def test_truncated_price_history_replays_same_past_positions_and_accounting():
    prices, meta, config = inputs()
    full = market_data_from_prices(prices, meta, config)
    prefix_config = {**config, "end": "2020-12"}
    prefix = market_data_from_prices(prices.loc[:"2020"], meta, prefix_config)
    first, second = {}, {}
    original, _ = run(full, prefix_config, first)
    replayed, _ = run(prefix, prefix_config, second)
    pd.testing.assert_frame_equal(first["exposure"], second["exposure"])
    pd.testing.assert_frame_equal(original, replayed)


def test_missing_held_return_raises_instead_of_becoming_zero_profit():
    prices, meta, config = inputs()
    data = market_data_from_prices(prices, meta, config)
    config = {**config, "end": "2020-03"}
    details = {}
    run(data, config, details)
    assert details["exposure"].loc["2020-03", "A"] != 0
    returns = data.returns.copy()
    returns.loc["2020-03", "A"] = np.nan
    with pytest.raises(ValueError, match="Missing held return at 2020-03.*A"):
        run(MarketData(returns, data.meta, data.prices), config)


def test_eligibility_uses_prior_signal_history_and_minimum_count():
    prices, meta, config = inputs()
    data = market_data_from_prices(prices, meta, config)
    returns = data.returns.copy()
    returns.loc["2019-12", "A"] = np.nan
    config = {**config, "end": "2020-01", "minimum_instruments": 2}
    ledger, _ = run(MarketData(returns, data.meta, data.prices), config)
    assert ledger.held_instruments.eq(0).all()
    assert ledger.turnover.eq(0).all()


def test_market_ending_before_final_month_does_not_disappear_retrospectively():
    prices, meta, config = inputs()
    prices.loc["2020-03":, "A"] = np.nan
    data = market_data_from_prices(prices, meta, {**config, "end": "2020-03"})
    assert "A" in data.returns
    with pytest.raises(ValueError, match="Missing held return at 2020-03.*A"):
        run(data, {**config, "end": "2020-03"})


def test_existing_report_directory_is_never_overwritten(tmp_path):
    marker = tmp_path / "stats.csv"
    marker.write_text("archived result")
    with pytest.raises(ValueError, match="new output directory"):
        main(tmp_path)
    assert marker.read_text() == "archived result"
