"""Portfolio risk from a covariance forecast."""

import numpy as np


def portfolio_risk(weights, covariance):
    variance = float(weights @ covariance @ weights)
    if variance < -1e-10 or not np.isfinite(variance):
        raise ValueError("Invalid forecast variance")
    return np.sqrt(max(variance, 0.0))
