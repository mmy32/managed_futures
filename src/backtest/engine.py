"""Monthly price-return proxy backtest with explicit timing and accounting."""

import numpy as np
import pandas as pd

from src.transaction_cost_model import CostModel, traded_exposure


def simulate(
    returns,
    targets,
    cost_model: CostModel,
    source=None,
    risk_free=None,
    liquidate=True,
    position_policy=None,
    source_known_at=None,
    instrument_details=None,
    roll_schedule=None,
):
    """Exposure in units of beginning-month NAV; futures collateral earns RF.

    Target exposures trade at the beginning endpoint (idealized). Units remain
    fixed during the month. Drifted end notionals are carried to next rebalance.
    Missing returns on held assets raise instead of becoming zero P&L.
    """
    assert targets.index.equals(returns.index) and targets.columns.equals(returns.columns)
    if source is not None and (
        not source.index.equals(returns.index) or not source.columns.equals(returns.columns)
    ):
        raise ValueError("Source schedule must match the return index and column order")
    if not np.isfinite(targets.to_numpy()).all():
        raise ValueError("Nonfinite target exposure")
    if roll_schedule is not None:
        roll_schedule.validate(returns)
    if source is not None and position_policy is not None:
        if source_known_at is None:
            raise ValueError("Policy-aware source costs require source_known_at dates")
        known = pd.to_datetime(source_known_at.reindex(returns.index))
        if (
            known.isna().any()
            or (known.to_numpy() >= returns.index.to_timestamp().to_numpy()).any()
        ):
            raise ValueError("Source schedule must be known before each return month")
    cash_rates = (
        pd.Series(0.0, index=returns.index)
        if risk_free is None
        else risk_free.reindex(returns.index)
    )
    if cash_rates.isna().any():
        raise ValueError("Missing collateral rate")
    previous = np.zeros(len(returns.columns))
    nav = 1.0
    prior_source = None
    rows, contributions, instrument_costs, holdings = [], [], [], []
    roll_costs, roll_notionals = [], []
    for i, month in enumerate(returns.index):
        w = targets.loc[month].to_numpy(dtype=float)
        switched = np.zeros(len(w), dtype=bool)
        if source is not None:
            current_source = source.loc[month].fillna("").to_numpy()
            if prior_source is not None:
                switched = (
                    (current_source != prior_source) & (current_source != "") & (prior_source != "")
                )
            prior_source = current_source
        diagnostics = {}
        roll_charge = None if roll_schedule is None else roll_schedule.charge(month)
        if position_policy is not None:
            # The policy sees past holdings and current targets, never this month's return.
            roll_options = {} if roll_charge is None else {"roll_charge": roll_charge}
            w, diagnostics = position_policy(
                month, previous.copy(), w.copy(), cost_model, switched, **roll_options
            )
            if not np.isfinite(w).all():
                raise ValueError("Nonfinite executed exposure")
        r = returns.loc[month].to_numpy(dtype=float)
        missing_held = ~np.isfinite(r) & (np.abs(w) > 1e-14)
        if missing_held.any():
            raise ValueError(
                f"Missing held return at {month}: {list(returns.columns[missing_held])}"
            )
        # Only unheld observations may be ignored in P&L.
        r = np.where(np.isfinite(r), r, 0.0)
        traded, source_extra = traded_exposure(w, previous, switched)
        turnover = float(traded.sum())
        ordinary_entry_cost = cost_model.cost(traded)
        rolled = (
            np.zeros(len(w)) if roll_charge is None else roll_charge.notional(w, previous, switched)
        )
        roll_fees = np.zeros(len(w)) if roll_charge is None else roll_charge.rate * rolled
        roll_fee = float(roll_fees.sum())
        entry_cost = ordinary_entry_cost + roll_fee
        gross = float(w @ r)
        funding = float(cash_rates.loc[month]) * (1 - entry_cost)
        final_month = liquidate and i == len(returns) - 1
        terminal_turnover = float(np.abs(w * (1 + r)).sum()) if final_month else 0.0
        exit_cost = cost_model.cost(np.abs(w * (1 + r))) if final_month else 0.0
        net = gross + funding - entry_cost - exit_cost
        if not np.isfinite(net) or 1 + net <= 0:
            raise ValueError(f"Nonfinite P&L or insolvent proxy account at {month}")
        ending_nav = nav * (1 + net)
        rows.append(
            dict(
                month=month,
                nav_start=nav,
                nav_end=ending_nav,
                gross_return=gross,
                collateral_income=funding,
                rebalance_cost=ordinary_entry_cost,
                liquidation_cost=exit_cost,
                cost=entry_cost + exit_cost,
                net_return=net,
                turnover=turnover + terminal_turnover + 2 * float(rolled.sum()),
                rebalance_turnover=turnover,
                source_switch_extra_turnover=source_extra,
                terminal_turnover=terminal_turnover,
                gross_exposure=float(np.abs(w).sum()),
                net_exposure=float(w.sum()),
                held_instruments=int((np.abs(w) > 1e-14).sum()),
                cost_cash=nav * (entry_cost + exit_cost),
                rebalance_instruments=int((traded > 1e-12).sum()),
                end_gross_before_liquidation=float(
                    np.abs(w * (1 + r)).sum() / (1 + gross + funding - entry_cost)
                ),
                **diagnostics,
            )
        )
        if roll_schedule is not None:
            rows[-1].update(
                roll_cost=roll_fee,
                ordinary_cost=ordinary_entry_cost + exit_cost,
                rolled_notional=float(rolled.sum()),
                roll_turnover=2 * float(rolled.sum()),
                ordinary_turnover=turnover + terminal_turnover,
            )
        contributions.append(w * r)
        # Allocate both source close/open trades and liquidation to the actual instrument.
        terminal_trades = (
            np.abs(w * (1 + r)) if liquidate and i == len(returns) - 1 else np.zeros(len(w))
        )
        instrument_costs.append(cost_model.instrument_cost(traded + terminal_trades) + roll_fees)
        roll_costs.append(roll_fees)
        roll_notionals.append(rolled)
        holdings.append(w.copy())
        previous = np.zeros(len(w)) if terminal_turnover else w * (1 + r) / (1 + net)
        nav = ending_nav
    ledger = pd.DataFrame(rows).set_index("month")
    attribution = pd.DataFrame(contributions, index=returns.index, columns=returns.columns)
    assert np.allclose(attribution.sum(axis=1), ledger.gross_return)
    assert np.allclose(ledger.nav_end, (1 + ledger.net_return).cumprod())
    assert np.allclose(
        ledger.net_return, ledger.gross_return + ledger.collateral_income - ledger.cost
    )
    if instrument_details is not None:
        instrument_details["cost"] = pd.DataFrame(
            instrument_costs, index=returns.index, columns=returns.columns
        )
        instrument_details["exposure"] = pd.DataFrame(
            holdings, index=returns.index, columns=returns.columns
        )
        if roll_schedule is not None:
            instrument_details["roll_cost"] = pd.DataFrame(
                roll_costs, index=returns.index, columns=returns.columns
            )
            instrument_details["ordinary_cost"] = (
                instrument_details["cost"] - instrument_details["roll_cost"]
            )
            instrument_details["rolled_notional"] = pd.DataFrame(
                roll_notionals, index=returns.index, columns=returns.columns
            )
        assert np.allclose(instrument_details["cost"].sum(axis=1), ledger.cost)
    return ledger, attribution
