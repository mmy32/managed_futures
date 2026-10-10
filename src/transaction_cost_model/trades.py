"""Trade size between two exposure vectors."""

import numpy as np


def traded_exposure(weights, previous, switched=None):
    """Absolute trade per market; a source switch closes the old and opens the new position."""
    traded = np.abs(weights - previous)
    extra = 0.0
    if switched is not None and switched.any():
        expanded = np.abs(weights[switched]) + np.abs(previous[switched])
        extra = float((expanded - traded[switched]).sum())
        traded[switched] = expanded
    return traded, extra
