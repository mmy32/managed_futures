"""Hierarchical risk parity (Lopez de Prado 2018, Ch. 16.4) as relative position sizes."""

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from src.risk_model import portfolio_risk


def cluster_variance(covariance, members):
    """Variance of the inverse-variance portfolio of `members`."""
    block = covariance[np.ix_(members, members)]
    weights = 1 / np.diag(block)
    weights /= weights.sum()
    return float(weights @ block @ weights)


def hrp_weights(covariance):
    """Positive weights summing to 1: single-linkage order, then top-down bisection.

    Each split gives the cluster with the smaller variance the larger share. No inversion.
    """
    n = len(covariance)
    if n == 1:
        return np.ones(1)
    sd = np.sqrt(np.diag(covariance))
    distance = np.sqrt((1 - np.clip(covariance / np.outer(sd, sd), -1, 1)) / 2)
    np.fill_diagonal(distance, 0.0)
    order = leaves_list(linkage(squareform(distance, checks=False), method="single"))
    weights = np.ones(n)
    clusters = [order]
    while clusters:
        clusters = [
            part
            for cluster in clusters
            if len(cluster) > 1
            for part in (cluster[: len(cluster) // 2], cluster[len(cluster) // 2 :])
        ]
        for left, right in zip(clusters[::2], clusters[1::2], strict=True):
            var_left, var_right = (
                cluster_variance(covariance, left),
                cluster_variance(covariance, right),
            )
            share = 1 - var_left / (var_left + var_right)
            weights[left] *= share
            weights[right] *= 1 - share
    return weights


class HrpSizing:
    """Replace the relative sizes inside each group by HRP, keeping each group's standalone risk.

    `within_class` makes each asset class a group (class risks stay as sized); otherwise all held
    markets form one group (total forecast risk stays as sized). With `signed` the clustering
    uses the covariance of the positions' own returns (sign-flipped for shorts); otherwise the
    raw covariance.
    """

    def __init__(self, within_class: bool, signed: bool):
        self.within_class = within_class
        self.signed = signed

    def __call__(self, raw, matrix, labels, active):
        held = active & (raw != 0)
        groups = (
            [held & (labels == c) for c in sorted(set(labels[held]))]
            if self.within_class
            else [held]
        )
        result = np.zeros_like(raw)
        for members in groups:
            if members.any():
                result[members] = self._resize(raw[members], matrix[np.ix_(members, members)])
        return result

    def _resize(self, raw, block):
        sign = np.sign(raw)
        flip = np.outer(sign, sign) if self.signed else 1.0
        shares = hrp_weights(block * flip)
        proposed = sign * shares
        target, achieved = portfolio_risk(raw, block), portfolio_risk(proposed, block)
        if achieved <= 0:
            raise ValueError("HRP positions have no forecast risk")
        return proposed * (target / achieved)
