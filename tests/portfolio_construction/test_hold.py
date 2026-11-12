import numpy as np
import pytest

from src.portfolio_construction.hold import HrpSizing, balance_classes, cap_class_risk, hrp_weights
from src.risk_model import portfolio_risk

LABELS = np.array(["A", "A", "B", "B", "C"])


def covariance(seed=3, n=5):
    rng = np.random.default_rng(seed)
    factor = rng.normal(size=(n, n))
    return factor @ factor.T / n + np.eye(n) * 0.05


def test_hrp_diagonal_covariance_is_inverse_variance():
    variances = np.array([0.04, 0.01, 0.09, 0.16])
    weights = hrp_weights(np.diag(variances))
    np.testing.assert_allclose(weights.sum(), 1.0)
    assert np.argmax(weights) == 1  # lowest variance gets the most weight
    assert (np.diff(weights[np.argsort(variances)]) <= 1e-12).all()


def test_hrp_weights_are_positive_sum_to_one_and_single_asset_is_trivial():
    weights = hrp_weights(covariance())
    assert (weights > 0).all()
    np.testing.assert_allclose(weights.sum(), 1.0)
    np.testing.assert_allclose(hrp_weights(np.array([[0.2]])), [1.0])


def test_hrp_sizing_keeps_sign_and_group_risk():
    matrix, raw = covariance(), np.array([0.1, -0.2, 0.15, 0.05, -0.1])
    active = np.ones(5, dtype=bool)
    for within in (True, False):
        sized = HrpSizing(within_class=within, signed=True)(raw, matrix, LABELS, active)
        np.testing.assert_array_equal(np.sign(sized), np.sign(raw))
        if within:
            for group in "ABC":
                members = LABELS == group
                np.testing.assert_allclose(
                    portfolio_risk(np.where(members, sized, 0), matrix),
                    portfolio_risk(np.where(members, raw, 0), matrix),
                )
        else:
            np.testing.assert_allclose(portfolio_risk(sized, matrix), portfolio_risk(raw, matrix))


def test_hrp_sizing_leaves_flat_and_inactive_markets_flat():
    matrix, raw = covariance(), np.array([0.1, 0.0, 0.15, 0.05, -0.1])
    active = np.array([True, True, True, False, True])
    sized = HrpSizing(within_class=False, signed=False)(raw, matrix, LABELS, active)
    assert sized[1] == 0 and sized[3] == 0


def test_balance_down_only_never_enlarges_a_class():
    matrix, raw = covariance(), np.array([0.3, -0.2, 0.01, 0.01, -0.02])
    active = np.ones(5, dtype=bool)
    both = balance_classes(raw.copy(), matrix, LABELS, active, 0.1)
    down = balance_classes(raw.copy(), matrix, LABELS, active, 0.1, scale_up=False)
    assert (np.abs(both) > np.abs(raw) + 1e-12).any()  # the quiet class is enlarged
    assert (np.abs(down) <= np.abs(raw) + 1e-12).all()


def test_class_cap_limits_each_share_and_never_scales_up():
    matrix, raw = covariance(), np.array([0.5, 0.4, 0.05, 0.05, 0.02])
    active = np.ones(5, dtype=bool)
    capped = cap_class_risk(raw.copy(), matrix, LABELS, active, 0.4)
    contribution = capped * (matrix @ capped)
    shares = {g: contribution[LABELS == g].sum() / contribution.sum() for g in "ABC"}
    assert max(shares.values()) <= 0.4 + 1e-4
    assert (np.abs(capped) <= np.abs(raw) + 1e-12).all()


def test_class_cap_below_one_over_k_is_raised_to_feasible_level():
    matrix, raw = covariance(), np.array([0.5, 0.4, 0.05, 0.05, 0.02])
    capped = cap_class_risk(raw.copy(), matrix, LABELS, np.ones(5, dtype=bool), 0.1)
    assert np.isfinite(capped).all()


def test_class_cap_leaves_a_book_inside_the_cap_unchanged():
    matrix, raw = np.eye(5) * 0.04, np.full(5, 0.1)  # class shares 0.4, 0.4, 0.2
    out = cap_class_risk(raw.copy(), matrix, LABELS, np.ones(5, dtype=bool), 0.5)
    np.testing.assert_allclose(out, raw)


@pytest.mark.parametrize("cap", [0.3, 0.5])
def test_class_cap_returns_flat_book_unchanged(cap):
    out = cap_class_risk(np.zeros(5), covariance(), LABELS, np.ones(5, dtype=bool), cap)
    np.testing.assert_array_equal(out, np.zeros(5))
