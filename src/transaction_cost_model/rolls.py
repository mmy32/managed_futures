"""Explicitly scheduled roll execution fees; no economic carry or price adjustment."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RollCharge:
    rate: float  # completed close/open event per unit of continuing notional
    due: np.ndarray

    def notional(self, weights, previous, switched=None):
        switched = np.zeros_like(self.due) if switched is None else switched
        continuing = self.due & ~switched & (weights * previous > 0)
        return np.where(continuing, np.minimum(np.abs(weights), np.abs(previous)), 0.0)

    def instrument_cost(self, weights, previous, switched=None):
        return self.rate * self.notional(weights, previous, switched)

    def cost(self, weights, previous, switched=None):
        return float(self.instrument_cost(weights, previous, switched).sum())


class RollSchedule:
    """Monthly beginning-period events known before the holding month.

    A source switch supersedes a coincident scheduled roll because its full
    close/open is already charged. Resizes pay ordinary fees on the change and
    roll fees only on same-direction overlapping holdings. Entries, exits and
    reversals therefore incur no additional scheduled-roll fee.
    """

    def __init__(self, due, known_at, bps, rate_basis="complete_roll"):
        if not np.isfinite(bps) or bps < 0:
            raise ValueError("Roll bps must be finite and nonnegative")
        if rate_basis not in {"complete_roll", "per_leg"}:
            raise ValueError("Roll rate basis must be complete_roll or per_leg")
        self.rate = bps / 10000 * (2 if rate_basis == "per_leg" else 1)
        self.due = due.copy()
        self.known_at = pd.to_datetime(known_at.copy())

    def validate(self, returns):
        if not self.due.index.equals(returns.index) or not self.due.columns.equals(returns.columns):
            raise ValueError("Roll schedule must match the return panel exactly")
        if (
            not all(pd.api.types.is_bool_dtype(d) for d in self.due.dtypes)
            or self.due.isna().any().any()
        ):
            raise ValueError("Roll schedule must contain observed boolean flags")
        if not self.known_at.index.equals(returns.index):
            raise ValueError("Roll known-at dates must match the return calendar")
        active = self.due.any(axis=1)
        late = self.known_at.isna() | self.known_at.ge(returns.index.to_timestamp())
        if (active & late).any():
            raise ValueError("Roll schedule must be known before the holding month")

    def charge(self, month):
        return RollCharge(self.rate, self.due.loc[month].to_numpy(dtype=bool))
