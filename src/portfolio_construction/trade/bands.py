"""No-trade bands around target positions."""

import numpy as np


def band_positions(previous, target, band):
    if not 0 <= band < 1:
        raise ValueError("Band must lie in [0,1)")
    same_direction = previous * target > 0
    width = band * np.abs(target)
    # np.clip handles shorts too: e.g. target -2%, band [-2.2%,-1.8%].
    return np.where(same_direction, np.clip(previous, target - width, target + width), target)
