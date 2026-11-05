import numpy as np
import pandas as pd
import pytest

from src.backtest.band_diagnostics import paired_bootstrap, turnover_components
from src.backtest.engine import simulate
from src.transaction_cost_model import LinearBpsCost


def test_trade_partition_includes_drift_reversals_source_legs_and_liquidation():
    index = pd.period_range("2000-01", periods=6, freq="M")
    returns = pd.DataFrame({"A": [0.1, 0, 0, 0, 0, 0]}, index=index)
    target = pd.DataFrame({"A": [0.5, 0.5, -0.5, -0.5, 0, 0.2]}, index=index)
    source = pd.DataFrame({"A": ["RL", "RL", "RL", "ER", "ER", "ER"]}, index=index)
    details = {}
    ledger, _ = simulate(returns, target, LinearBpsCost(2), source, instrument_details=details)
    trades = turnover_components(returns, details["exposure"], ledger, source)
    assert trades.entries.iloc[0] == 0.5
    assert trades.resizes.iloc[1] == pytest.approx(0.55 / (1 + 0.05 - 0.0001) - 0.5)
    assert trades.reversals.iloc[2] > 1
    assert trades.source_switches.iloc[3] > 1
    assert trades.exits.iloc[4] > 0.5
    assert trades.entries.iloc[5] == 0.2
    assert trades.terminal_liquidation.iloc[5] == 0.2
    np.testing.assert_allclose(trades.sum(axis=1) * 2 / 10000, ledger.cost)


def test_paired_bootstrap_preserves_pairing_and_has_exact_constant_difference():
    differences = pd.DataFrame({"gain": np.repeat(0.001, 48), "loss": np.repeat(-0.001, 48)})
    result = paired_bootstrap(differences, 12, 1000, 42, family_size=2)
    np.testing.assert_allclose(
        result.loc["gain", ["mean_difference_ann", "ci_low", "ci_high"]], 0.012
    )
    np.testing.assert_allclose(
        result.loc["loss", ["mean_difference_ann", "ci_low", "ci_high"]], -0.012
    )
    varying = pd.DataFrame({"a": np.arange(48) / 10000, "b": -np.arange(48) / 10000})
    paired = paired_bootstrap(varying, 12, 1000, 42, family_size=2)
    assert paired.loc["a", "ci_low"] == pytest.approx(-paired.loc["b", "ci_high"])
    assert paired.loc["a", "family_ci_low"] <= paired.loc["a", "ci_low"]
    pd.testing.assert_frame_equal(paired, paired_bootstrap(varying, 12, 1000, 42, family_size=2))


def test_bootstrap_rejects_missing_pairs():
    with pytest.raises(ValueError, match="finite"):
        paired_bootstrap(pd.DataFrame({"a": [0, np.nan]}), 1, 100, 1)
