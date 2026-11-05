"""Inverse-volatility position sizes from a direction signal."""

from collections.abc import Iterable

import numpy as np
import pandas as pd


class InverseVolatilitySizer:
    """Equal-risk sizes: scale / volatility per market, divided by the eligible count.

    A market is eligible with a known signal and a positive volatility, unless excluded.
    Fewer than `minimum_instruments` eligible markets leave the portfolio flat.
    The scale is an instrument scale, not a portfolio volatility target.
    """

    def __init__(
        self,
        scale: float,
        volatility_floor: float,
        minimum_instruments: int,
        excluded: Iterable[str] = (),
    ):
        self.scale = scale
        self.volatility_floor = volatility_floor
        self.minimum_instruments = minimum_instruments
        self.excluded = frozenset(excluded)

    def eligibility(self, signal: pd.DataFrame, vol: pd.DataFrame) -> pd.DataFrame:
        eligible = signal.notna() & vol.notna() & vol.gt(0)
        for market in self.excluded:
            if market in eligible:
                eligible[market] = False
        return eligible

    def weights(self, signal: pd.DataFrame, vol: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (signed weights, eligibility) for lagged signal and volatility frames."""
        eligible = self.eligibility(signal, vol)
        inverse = (1 / vol.clip(lower=self.volatility_floor)).where(eligible, 0.0)
        count = eligible.sum(axis=1)
        magnitude = inverse.mul(self.scale).div(count.replace(0, np.nan), axis=0).fillna(0.0)
        magnitude.loc[count < self.minimum_instruments] = 0.0
        return magnitude * signal.fillna(0), eligible
