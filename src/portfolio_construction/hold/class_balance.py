"""Optional class adjustments to the sized book: equal class risk budgets, or a cap on any class."""

import numpy as np

from src.risk_model import portfolio_risk


def balance_factors(raw, matrix, labels, active, risk_ceiling):
    """Factor that brings each active class's standalone risk to an equal share of the ceiling."""
    classes = sorted(set(labels[np.flatnonzero(active)]))
    budget = risk_ceiling / np.sqrt(len(classes))
    factors = {}
    for group in classes:
        standalone = portfolio_risk(np.where((labels == group) & active, raw, 0.0), matrix)
        if standalone > 0:
            factors[group] = budget / standalone
    return factors


def balance_classes(raw, matrix, labels, active, risk_ceiling, scale_up=True):
    """Scale each asset class to an equal share of the risk ceiling.

    With `scale_up` False a class below its budget keeps its raw size (reduce only).
    """
    for group, factor in balance_factors(raw, matrix, labels, active, risk_ceiling).items():
        raw[(labels == group) & active] *= factor if scale_up else min(1.0, factor)
    return raw


def class_shares(weights, matrix, labels, classes):
    """Euler share of forecast variance by class: sum of w_i (Qw)_i over the class / w'Qw."""
    contribution = weights * (matrix @ weights)
    total = contribution.sum()
    return {group: contribution[labels == group].sum() / total for group in classes}


def cap_class_risk(raw, matrix, labels, active, cap, passes=500, tolerance=1e-4):
    """Scale down any class whose share of forecast variance exceeds `cap`; never scale up.

    With K active classes no cap below 1/K is feasible, so the cap is raised to 1/K.
    """
    held = active & (raw != 0)
    classes = sorted(set(labels[np.flatnonzero(held)]))
    if not classes:
        return raw
    limit = max(cap, 1 / len(classes))
    for _ in range(passes):
        shares = class_shares(raw, matrix, labels, classes)
        worst = max(shares, key=shares.get)
        if shares[worst] <= limit + tolerance:
            return raw
        members = (labels == worst) & held
        low, high = 0.0, 1.0
        for _ in range(60):
            middle = (low + high) / 2
            trial = raw.copy()
            trial[members] *= middle
            if class_shares(trial, matrix, labels, classes)[worst] <= limit:
                low = middle
            else:
                high = middle
        raw[members] *= low
    raise ValueError(
        f"Class risk cap did not converge: worst share {shares[worst]:.4f} > {limit:.4f}"
    )
