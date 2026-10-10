"""Transaction cost models: cost as a fraction of beginning-month NAV."""

from typing import Protocol

import numpy as np

BPS = 10_000


class CostModel(Protocol):
    def cost(self, traded: np.ndarray) -> float:
        """Total cost of trading the given absolute exposures."""
        ...

    def instrument_cost(self, traded: np.ndarray) -> np.ndarray:
        """Cost attributed to each market; sums to cost()."""
        ...


class ZeroCost:
    """Gross returns, as in the Moskowitz-Ooi-Pedersen baseline."""

    def cost(self, traded: np.ndarray) -> float:
        return 0.0

    def instrument_cost(self, traded: np.ndarray) -> np.ndarray:
        return np.zeros(len(traded))


class LinearBpsCost:
    """bps per unit of absolute traded exposure."""

    def __init__(self, bps: float):
        if bps < 0:
            raise ValueError("Trading costs must be nonnegative")
        self.rate = bps / BPS

    def cost(self, traded: np.ndarray) -> float:
        return self.rate * float(traded.sum())

    def instrument_cost(self, traded: np.ndarray) -> np.ndarray:
        return self.rate * traded
