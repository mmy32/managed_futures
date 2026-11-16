import numpy as np
import pandas as pd
import pytest
from run_pc_hold import summary_row, variant_walk_forward

CONFIG = {"walk_forward": {"train_months": 60, "test_months": 12,
                            "minimum_test_months": 12}}


def candidates():
    dates = pd.period_range("2000-01", periods=180, freq="M")
    rng = np.random.default_rng(9723)
    return pd.DataFrame({"baseline": rng.normal(0.004, 0.025, len(dates)),
                         "enhanced": rng.normal(0.005, 0.027, len(dates))}, index=dates)


def test_walk_forward_choices_cannot_depend_on_future_returns_or_test_outcomes():
    nets = candidates()
    original = variant_walk_forward(nets, "baseline", CONFIG)
    cutoff = pd.Period("2010-01", freq="M")
    altered = nets.copy()
    altered.loc[cutoff:, "enhanced"] += 0.5
    changed = variant_walk_forward(altered, "baseline", CONFIG)
    prior = pd.PeriodIndex(original.test_end, freq="M") < cutoff
    pd.testing.assert_frame_equal(original.loc[prior], changed.loc[prior])
    # The first affected fold has changed outcomes but the same past-only choice.
    starts_at_cutoff = original.test_start.eq(str(cutoff))
    pd.testing.assert_series_equal(original.loc[starts_at_cutoff, "chosen"],
                                   changed.loc[starts_at_cutoff, "chosen"])
    assert changed.chosen.iloc[-1] == "enhanced"
    assert (pd.PeriodIndex(original.train_end, freq="M")
            < pd.PeriodIndex(original.test_start, freq="M")).all()
    assert "portfolio_sharpe" not in original and "stitched_return" not in original


def test_walk_forward_selection_matches_the_training_window_only():
    nets = candidates()
    folds = variant_walk_forward(nets, "baseline", CONFIG)
    for fold in folds.itertuples(index=False):
        training = nets.loc[fold.train_start:fold.train_end]
        expected = (training.mean() / training.std(ddof=1)).idxmax()
        assert fold.chosen == expected
        testing = nets.loc[fold.test_start:fold.test_end]
        assert fold.candidate_minus_baseline_mean_ann == pytest.approx(
            (testing[expected] - testing.baseline).mean() * 12
        )


@pytest.mark.parametrize("invalid", ["empty", "short", "missing_month", "nonfinite", "flat"])
def test_walk_forward_rejects_unusable_selection_data(invalid):
    nets = candidates()
    if invalid == "empty":
        nets = nets.iloc[:0]
    elif invalid == "short":
        nets = nets.iloc[:65]
    elif invalid == "missing_month":
        nets = nets.drop(index=nets.index[20])
    elif invalid == "nonfinite":
        nets.iloc[0, 0] = np.nan
    else:
        nets[:] = 0.0
    with pytest.raises(ValueError):
        variant_walk_forward(nets, "baseline", CONFIG)


def test_headline_metrics_are_actual_fixed_variant_returns(monkeypatch):
    returns = candidates().baseline.iloc[:24]
    ledger = pd.DataFrame({"net_return": returns, "turnover": 1.0, "cost": 0.001,
                           "cost_cash": 0.001, "gross_exposure": 2.0})
    diagnostics = pd.DataFrame({"effective_bets": [4.0], "max_class_share": [0.6]})
    monkeypatch.setattr("run_pc_hold.risk_diagnostics",
                        lambda _: (None, {"realized_predicted_ratio": 1.1}))
    result = summary_row("baseline", ledger, diagnostics, {"concentration_share": 0.4})
    assert result["mean_ann"] == pytest.approx(returns.mean() * 12)
    assert result["cagr"] == pytest.approx((1 + returns).prod() ** (12 / len(returns)) - 1)
    assert result["mean_cost_ann"] == pytest.approx(0.012)
    assert not any(name.startswith("matched_") for name in result)
