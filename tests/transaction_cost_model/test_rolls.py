import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.backtest.roll_events import execution_journal
from src.portfolio_construction import BandPolicy, PortfolioLimits
from src.transaction_cost_model import LinearBpsCost, traded_exposure
from src.transaction_cost_model.rolls import RollCharge, RollSchedule


@pytest.mark.parametrize(
    "previous,weights,switched,expected",
    [
        (1, 1, False, 1),
        (1, 1.5, False, 1),
        (1, 0.5, False, 0.5),
        (-1, -1.5, False, 1),
        (0, 0, False, 0),
        (0, 1, False, 0),
        (1, 0, False, 0),
        (1, -1, False, 0),
        (1, 1.5, True, 0),
    ],
)
def test_roll_only_charges_continuing_overlap(previous, weights, switched, expected):
    quote = RollCharge(0.0002, np.array([True]))
    w, p, changed = np.array([weights]), np.array([previous]), np.array([switched])
    assert quote.notional(w, p, changed)[0] == expected
    assert quote.cost(w, p, changed) == pytest.approx(expected * 0.0002)


def panels():
    index = pd.period_range("2000-01", periods=3, freq="M")
    returns = pd.DataFrame({"A": [0.0, 0.0, 0.0]}, index=index)
    targets = pd.DataFrame({"A": [0.5, 0.5, 0.5]}, index=index)
    due = pd.DataFrame(True, index=index, columns=["A"])
    known = pd.Series(pd.Timestamp("1999-12-01"), index=index)
    return returns, targets, due, known


def test_complete_roll_and_per_leg_quotes_match_with_resize():
    r, _, due, known = panels()
    completed = RollSchedule(due, known, 4, "complete_roll")
    per_leg = RollSchedule(due, known, 2, "per_leg")
    completed.validate(r)
    w, previous, switched = np.array([1.5]), np.array([1.0]), np.array([False])
    a, b = completed.charge(r.index[0]), per_leg.charge(r.index[0])
    ordinary = LinearBpsCost(2).cost(traded_exposure(w, previous, switched)[0])
    assert a.cost(w, previous) == b.cost(w, previous)
    assert ordinary + a.cost(w, previous) == pytest.approx((1 + 1.5) * 2 / 10000)


def test_unchanged_holding_rolls_and_all_cost_components_reconcile():
    r, target, due, known = panels()
    details = {}
    ledger, gross = simulate(
        r,
        target,
        LinearBpsCost(0),
        roll_schedule=RollSchedule(due, known, 2),
        instrument_details=details,
    )
    assert ledger.roll_cost.iloc[0] == 0  # New entry already opens the new contract.
    assert ledger.rebalance_turnover.iloc[1] == 0
    assert ledger.roll_cost.iloc[1] == pytest.approx(0.0001)
    np.testing.assert_allclose(ledger.ordinary_cost + ledger.roll_cost, ledger.cost)
    np.testing.assert_allclose(ledger.ordinary_turnover + ledger.roll_turnover, ledger.turnover)
    np.testing.assert_allclose(details["ordinary_cost"] + details["roll_cost"], details["cost"])
    np.testing.assert_allclose(gross.sum(axis=1) - details["cost"].sum(axis=1), ledger.net_return)


def test_source_switch_suppresses_duplicate_roll_and_terminal_fee_is_ordinary():
    r, target, due, known = panels()
    source = pd.DataFrame({"A": ["RL", "ER", "ER"]}, index=r.index)
    ledger, _ = simulate(
        r, target, LinearBpsCost(2), source, roll_schedule=RollSchedule(due, known, 2)
    )
    assert ledger.roll_cost.iloc[1] == 0
    assert ledger.rebalance_turnover.iloc[1] > 1  # Fee-adjusted drift plus new exposure.
    assert ledger.liquidation_cost.iloc[-1] == pytest.approx(0.5 * 2 / 10000)
    assert ledger.ordinary_cost.iloc[-1] == pytest.approx(
        ledger.rebalance_cost.iloc[-1] + ledger.liquidation_cost.iloc[-1]
    )


def test_policy_enforces_limits_after_combined_trade_and_roll_fees():
    month = pd.Period("2000-01", "M")
    policy = BandPolicy({month: np.array([[0.0001]])}, PortfolioLimits(3, 0.1), 0.1)
    quote = RollCharge(0.0002, np.array([True]))
    executed, diagnostics = policy(
        month,
        np.array([3.0]),
        np.array([3.0]),
        LinearBpsCost(2),
        np.array([False]),
        roll_charge=quote,
    )
    assert executed[0] == pytest.approx(3 * (1 - 0.0006))
    assert diagnostics["gross_after_cost"] == pytest.approx(3)
    assert diagnostics["limit_override"]


def test_no_roll_schedule_preserves_default_and_zero_rate_matches_common_columns():
    r, target, due, known = panels()
    original, _ = simulate(r, target, LinearBpsCost(2))
    revised, _ = simulate(r, target, LinearBpsCost(2), roll_schedule=RollSchedule(due, known, 0))
    common = original.columns.difference(["turnover"])
    pd.testing.assert_frame_equal(original[common], revised[common])
    np.testing.assert_allclose(original.turnover, revised.ordinary_turnover)


def test_roll_schedule_rejects_lookahead_and_missing_flags():
    r, _, due, known = panels()
    late = pd.Series(r.index.to_timestamp(), index=r.index)
    with pytest.raises(ValueError, match="before"):
        RollSchedule(due, late, 2).validate(r)
    missing = due.astype("boolean")
    missing.iloc[0, 0] = pd.NA
    with pytest.raises(ValueError, match="boolean"):
        RollSchedule(missing, known, 2).validate(r)


@pytest.mark.parametrize("rate", [-1, np.nan, np.inf])
def test_invalid_roll_rates_fail(rate):
    _, _, due, known = panels()
    with pytest.raises(ValueError, match="finite"):
        RollSchedule(due, known, rate)


def test_future_roll_events_do_not_change_past_holdings_or_pnl():
    r, target, due, known = panels()
    first, _ = simulate(r, target, LinearBpsCost(2), roll_schedule=RollSchedule(due, known, 2))
    altered = due.copy()
    altered.iloc[-1] = False
    second, _ = simulate(r, target, LinearBpsCost(2), roll_schedule=RollSchedule(altered, known, 2))
    pd.testing.assert_frame_equal(first.iloc[:-1], second.iloc[:-1])


@pytest.mark.parametrize("switch", [False, True])
@pytest.mark.parametrize("liquidate", [False, True])
def test_event_journal_cost_and_notional_match_simulator(switch, liquidate):
    r, target, due, known = panels()
    target.iloc[1] = 0.7
    target.iloc[2] = -0.4
    source = pd.DataFrame(
        {"A": ["RL", "ER" if switch else "RL", "ER" if switch else "RL"]}, index=r.index
    )
    details = {}
    ledger, _ = simulate(
        r,
        target,
        LinearBpsCost(2),
        source,
        roll_schedule=RollSchedule(due, known, 2),
        instrument_details=details,
        liquidate=liquidate,
    )
    events = execution_journal(r, source, ledger, details, 2, 2)
    grouped = events.groupby("component").cost_nav.sum()
    assert grouped.get("roll", 0) == pytest.approx(ledger.roll_cost.sum())
    assert grouped.ordinary == pytest.approx(ledger.ordinary_cost.sum())
    assert (events.event == "assumed_roll_open").sum() == (0 if switch else 1)


def test_roll_fees_reduce_collateral_before_cash_income():
    r, target, due, known = panels()
    cash = pd.Series(0.001, index=r.index)
    ledger, _ = simulate(
        r, target, LinearBpsCost(2), risk_free=cash, roll_schedule=RollSchedule(due, known, 2)
    )
    np.testing.assert_allclose(
        ledger.collateral_income, cash * (1 - ledger.rebalance_cost - ledger.roll_cost)
    )
