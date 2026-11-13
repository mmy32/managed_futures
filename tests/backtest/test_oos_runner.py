import copy
import hashlib
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.backtest import oos_runner
from src.backtest.hrp_comparison import load_comparison
from src.backtest.oos_inputs import load_bundle, strategy_inputs
from src.risk_model import daily_returns


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    spec, _, _ = load_comparison()
    base = {
        "start": "2000-01", "end": "2014-12", "signal_months": 12,
        "information_lag_months": 1, "instrument_volatility_scale": 0.4,
        "minimum_instruments": 2, "exclude_from_strategy": {}, "hold_sizing": "hrp_within_class",
    }
    risk = {
        "base_config": spec["base_config"], "volatility_months": 12,
        "volatility_floor_annual": 0.02, "correlation_shrinkage": 0.5,
        "gross_cap": 3.0, "portfolio_risk_ceiling": 0.1,
        "primary_cost_bps": 2, "primary_band": 0.1,
        "risk_model": {"type": "dcc_garch", "correlation_shrinkage": 0.1,
                       "rescale": {"window": 12, "minimum": 6}},
        "source_selection": {"minimum_history": 3, "decision_lag_months": 2},
    }
    monkeypatch.setattr(oos_runner, "load_comparison", lambda: copy.deepcopy((spec, base, risk)))
    declaration = {
        "evaluation_start": "2017-04", "evaluation_end": "2017-09", "shadow_start": "2016-01",
        "primary_information_lag_months": 1, "information_lags_months": [1, 2],
        "initial_positions": "flat", "liquidate_at_end": True,
        "execution_convention": "idealized_prior_endpoint", "cash_interest": "zero",
        "ordinary_cost_bps": 2, "trading_band": 0.1, "universe": ["A", "B", "RL", "C"],
        "provenance": {key: "synthetic fixture" for key in (
            "vendor", "vintage", "timezone", "price_definition", "continuous_contract_adjustment",
            "availability_convention",
        )},
    }
    declaration_path = tmp_path / "declaration.json"
    declaration_path.write_text(json.dumps(declaration))
    meta_path = tmp_path / "AssetMapCsv.csv"
    pd.DataFrame({"ID": declaration["universe"], "AssetClass": ["EQ", "EQ", "FI", "FI"]}).to_csv(
        meta_path, index=False
    )
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    index = pd.bdate_range("2013-01-01", "2017-12-29")
    rng = np.random.default_rng(5260)
    common = rng.normal(0.0002, 0.004, len(index))
    for name in [*declaration["universe"], "ER"]:
        daily = common + rng.normal(0.0002, 0.006, len(index))
        pd.DataFrame({"Close": 100 * (1 + daily).cumprod()}, index=index).to_csv(prices_dir / f"{name}.csv")
    return declaration_path, prices_dir, meta_path, declaration, base, risk


def test_prepare_locks_inputs_without_calculating_performance(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    record = oos_runner.prepare(declaration, prices, meta, prepared)
    assert record["status"] == "prepared_not_evaluated"
    assert record["coverage"]["evaluation_start"] == "2017-04"
    assert set(record["input_files"]) == {"asset_map", "price:A", "price:B", "price:RL", "price:C", "price:ER"}
    assert not (prepared / "assessment").exists()
    with zipfile.ZipFile(prepared / "source_snapshot.zip") as snapshot:
        assert set(snapshot.namelist()) == set(record["source_sha256"])
        assert all(hashlib.sha256(snapshot.read(name)).hexdigest() == expected
                   for name, expected in record["source_sha256"].items())
    assert oos_runner.verify_preparation(prepared) == record
    with pytest.raises(ValueError, match="new preparation"):
        oos_runner.prepare(declaration, prices, meta, prepared)


def test_changed_input_blocks_assessment_before_results(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    with (prices / "A.csv").open("a") as stream:
        stream.write("2018-01-01,100\n")
    with pytest.raises(ValueError, match="Input files changed"):
        oos_runner.run(prepared)
    assert not (prepared / "assessment").exists()


def test_changed_environment_blocks_assessment_before_results(bundle, tmp_path, monkeypatch):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    versions = oos_runner.environment_versions()
    monkeypatch.setattr(oos_runner, "environment_versions", lambda: {**versions, "numpy": "changed"})
    with pytest.raises(ValueError, match="dependency versions changed"):
        oos_runner.run(prepared)
    assert not (prepared / "assessment").exists()


def test_changed_source_blocks_assessment_before_results(bundle, tmp_path, monkeypatch):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    code = oos_runner.source_hashes()
    monkeypatch.setattr(oos_runner, "source_hashes", lambda: {**code, "changed.py": "changed"})
    with pytest.raises(ValueError, match="Source or configuration changed"):
        oos_runner.run(prepared)
    assert not (prepared / "assessment").exists()


def test_changed_source_snapshot_blocks_assessment_before_results(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    with (prepared / "source_snapshot.zip").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="source snapshot changed"):
        oos_runner.run(prepared)
    assert not (prepared / "assessment").exists()


def test_missing_rl_fallback_file_blocks_preparation(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    (prices / "ER.csv").unlink()
    prepared = tmp_path / "prepared"
    with pytest.raises(ValueError, match="Missing declared input files"):
        oos_runner.prepare(declaration, prices, meta, prepared)
    assert not prepared.exists()


def test_source_switch_uses_each_sources_own_daily_returns(bundle):
    _, prices_dir, meta, declaration, base, risk = bundle
    prices, _, _, _ = load_bundle(prices_dir, meta, declaration, base, risk)
    _, source, _, daily = strategy_inputs(
        prices, declaration["universe"], risk, pd.Period(declaration["evaluation_end"], "M")
    )
    original = daily_returns(prices.loc[:pd.Period(declaration["evaluation_end"], "M").end_time])
    source_by_day = source.RL.reindex(daily.index.to_period("M"))
    assert source_by_day.eq("RL").any() and source_by_day.eq("ER").any()
    for name in ("RL", "ER"):
        mask = source_by_day.eq(name).to_numpy()
        np.testing.assert_allclose(daily.RL.to_numpy()[mask], original[name].to_numpy()[mask],
                                   equal_nan=True)


def test_strategy_inputs_match_a_truncated_price_history(bundle):
    _, prices_dir, meta, declaration, base, risk = bundle
    prices, _, _, _ = load_bundle(prices_dir, meta, declaration, base, risk)
    end = pd.Period(declaration["evaluation_end"], "M")
    cutoff = pd.Period("2017-06", "M")
    full = strategy_inputs(prices, declaration["universe"], risk, end)
    prefix = strategy_inputs(prices.loc[:cutoff.end_time], declaration["universe"], risk, cutoff)
    for full_monthly, prefix_monthly in zip(full[:3], prefix[:3], strict=True):
        if isinstance(full_monthly, pd.DataFrame):
            pd.testing.assert_frame_equal(full_monthly.loc[:cutoff], prefix_monthly)
        else:
            pd.testing.assert_series_equal(full_monthly.loc[:cutoff], prefix_monthly)
    pd.testing.assert_frame_equal(full[3].loc[:cutoff.end_time], prefix[3])


@pytest.mark.parametrize(
    "change, message",
    [
        ({"evaluation_start": "2014-12"}, "follow development"),
        ({"shadow_start": "2017-03"}, "Shadow period"),
        ({"information_lags_months": [1]}, "information lags"),
        ({"universe": ["A", "../B"]}, "market IDs"),
    ],
)
def test_invalid_declarations_fail_before_preparation(bundle, tmp_path, change, message):
    declaration_path, prices, meta, declaration, _, _ = bundle
    declaration.update(change)
    declaration_path.write_text(json.dumps(declaration))
    prepared = tmp_path / "prepared"
    with pytest.raises(ValueError, match=message):
        oos_runner.prepare(declaration_path, prices, meta, prepared)
    assert not prepared.exists()


def test_run_produces_four_matched_ledgers_from_prepared_inputs(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    results = oos_runner.run(prepared)
    status = json.loads((prepared / "assessment/status.json").read_text())
    metrics = pd.read_csv(results / "metrics.csv")
    assert status["status"] == "complete" and status["complete_results_published"]
    assert set(zip(metrics.information_lag_months, metrics.portfolio, strict=True)) == {
        (1, "baseline"), (1, "enhanced"), (2, "baseline"), (2, "enhanced")
    }
    assert (metrics.months == 6).all()
    output_hashes = json.loads((results / "output_sha256.json").read_text())
    assert all(oos_runner.digest(results / name) == expected for name, expected in output_hashes.items())
    for lag in (1, 2):
        paired = pd.read_csv(results / f"lag{lag}_paired_returns.csv", index_col=0)
        assert len(paired) == 6
        np.testing.assert_allclose(paired.enhanced_minus_baseline,
                                   paired.enhanced_net - paired.baseline_net)
        for name in ("baseline", "enhanced"):
            ledger = pd.read_csv(results / f"lag{lag}_{name}_ledger.csv.gz", index_col=0)
            exposure = pd.read_csv(results / f"lag{lag}_{name}_exposure.csv.gz", index_col=0)
            assert ledger.nav_start.iloc[0] == 1.0
            assert ledger.rebalance_turnover.iloc[0] == pytest.approx(exposure.iloc[0].abs().sum())
            np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost)
            assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
    with pytest.raises(ValueError, match="already exists"):
        oos_runner.run(prepared)


def test_missing_held_return_fails_without_publishing_results(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    path = prices / "A.csv"
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame = frame.loc[~((frame.index.year == 2017) & (frame.index.month == 7))]
    frame.to_csv(path)
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    with pytest.raises(ValueError, match="Missing held return"):
        oos_runner.run(prepared)
    status = json.loads((prepared / "assessment/status.json").read_text())
    assert status["status"] == "failed" and not status["complete_results_published"]
    assert not (prepared / "assessment/results").exists()


def test_staggered_histories_do_not_fit_before_the_shadow_start(bundle, tmp_path):
    declaration, prices, meta, _, _, _ = bundle
    for name in ("B", "RL", "C", "ER"):
        path = prices / f"{name}.csv"
        frame = pd.read_csv(path, index_col=0, parse_dates=True).loc["2014-01-01":]
        frame.to_csv(path)
    prepared = tmp_path / "prepared"
    oos_runner.prepare(declaration, prices, meta, prepared)
    results = oos_runner.run(prepared)
    assert (results / "metrics.csv").is_file()
