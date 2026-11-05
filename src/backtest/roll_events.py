"""An inspectable execution journal in beginning-month NAV units, not contract counts."""

import numpy as np
import pandas as pd


def _ordinary_legs(previous, weight, switched):
    if switched:
        return [("source_close", -previous), ("source_open", weight)]
    if previous * weight < 0:
        return [("reversal_close", -previous), ("reversal_open", weight)]
    kind = "entry" if previous == 0 else "exit" if weight == 0 else "resize"
    return [(kind, weight - previous)]


def execution_journal(returns, source, ledger, details, trade_bps, complete_roll_bps):
    source = source.fillna("")
    exposure = details["exposure"]
    previous = (
        (exposure.shift(1) * (1 + returns.fillna(0).shift(1)))
        .div(1 + ledger.net_return.shift(1), axis=0)
        .fillna(0)
    )
    rolled = details.get("rolled_notional", exposure * 0)
    rows = []
    for i, month in enumerate(returns.index):
        for market in returns.columns:
            old, new = previous.loc[month, market], exposure.loc[month, market]
            label = source.loc[month, market]
            prior_label = source.iloc[i - 1][market] if i else label
            switched = i > 0 and label != prior_label and label != "" and prior_label != ""
            for kind, signed in _ordinary_legs(old, new, switched):
                _append(rows, month, market, kind, signed, trade_bps, "ordinary", "beginning")
            q = rolled.loc[month, market] * np.sign(new)
            _append(
                rows,
                month,
                market,
                "assumed_roll_close",
                -q,
                complete_roll_bps / 2,
                "roll",
                "beginning",
            )
            _append(
                rows,
                month,
                market,
                "assumed_roll_open",
                q,
                complete_roll_bps / 2,
                "roll",
                "beginning",
            )
            if i == len(returns) - 1 and ledger.terminal_turnover.iloc[i] > 0:
                terminal = -new * (1 + returns.loc[month, market]) if new != 0 else 0
                _append(rows, month, market, "liquidation", terminal, trade_bps, "ordinary", "end")
    events = pd.DataFrame(
        rows,
        columns=[
            "month",
            "market",
            "event",
            "signed_exposure",
            "notional_nav",
            "cost_nav",
            "component",
            "timing",
        ],
    )
    totals = (
        events.groupby("month")[["notional_nav", "cost_nav"]]
        .sum()
        .reindex(ledger.index.astype(str), fill_value=0)
    )
    np.testing.assert_allclose(totals.notional_nav, ledger.turnover, atol=1e-12)
    np.testing.assert_allclose(totals.cost_nav, ledger.cost, atol=1e-12)
    return events


def _append(rows, month, market, kind, signed, bps, component, timing):
    if signed != 0:
        rows.append(
            (
                str(month),
                market,
                kind,
                signed,
                abs(signed),
                abs(signed) * bps / 10000,
                component,
                timing,
            )
        )
