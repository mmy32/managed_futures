"""Optional class balance: scale each asset class to an equal share of the risk ceiling."""

import numpy as np

from src.risk_model import portfolio_risk


def balance_classes(raw, matrix, labels, active, risk_ceiling):
    """Scale each asset class to an equal share of the risk ceiling."""
    classes = sorted(set(labels[np.flatnonzero(active)]))
    budget = risk_ceiling / np.sqrt(len(classes))
    for group in classes:
        chosen = (labels == group) & active
        standalone = portfolio_risk(np.where(chosen, raw, 0.0), matrix)
        if standalone > 0:
            raw[chosen] *= budget / standalone
    return raw
