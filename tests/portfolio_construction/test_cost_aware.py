import numpy as np
import pytest

pytest.importorskip("cvxpy")

from src.portfolio_construction.trade.cost_aware import CostAwarePolicy, SolverSettings
from src.portfolio_construction.scale import PortfolioLimits
from src.transaction_cost_model import LinearBpsCost, ZeroCost, traded_exposure


def policy(matrix, gamma=10, limits=PortfolioLimits(3, 1), **kwargs):
    return CostAwarePolicy({0: np.array(matrix)}, limits, gamma, **kwargs)


@pytest.mark.parametrize("sign", [1, -1])
def test_scalar_solution_matches_analytic_soft_threshold(sign):
    model = policy([[0.04]])
    weights, diagnostics = model(
        0, np.array([0.0]), np.array([sign * 0.5]), LinearBpsCost(1.5), np.array([False])
    )
    expected = sign * (0.5 - 0.00015 / (10 * 0.04 / 12))
    np.testing.assert_allclose(weights, [expected], atol=1e-7)
    assert diagnostics["solver_status"] == "optimal"


def test_source_switch_uses_close_plus_open_not_net_trade():
    model = policy([[0.04]])
    previous, target = np.array([0.5]), np.array([0.5])
    held, _ = model(0, previous, target, LinearBpsCost(1.5), np.array([False]))
    switched, diagnostic = model(0, previous, target, LinearBpsCost(1.5), np.array([True]))
    np.testing.assert_allclose(held, target, atol=1e-7)
    np.testing.assert_allclose(switched, [0.4955], atol=1e-7)
    fee = 0.00015 * (abs(previous[0]) + abs(switched[0]))
    assert diagnostic["tracking_objective"] == pytest.approx(
        10 / 24 * 0.04 * (switched[0] - target[0])**2 + fee
    )
    assert len(model.problems) == 1


def test_forced_exits_are_charged_inside_binding_gross_limit():
    model = policy([[0, 0], [0, 0.0004]], gamma=100, limits=PortfolioLimits(3, 1))
    previous, target = np.array([2.0, 0]), np.array([0, 4.0])
    weights, diagnostics = model(0, previous, target, LinearBpsCost(1.5), np.array([False]*2))
    expected = 3 * (1 - 0.00015 * 2) / (1 + 3 * 0.00015)
    assert weights[0] == 0
    assert weights[1] == pytest.approx(expected, abs=1e-7)
    assert diagnostics["gross_after_cost"] == pytest.approx(3, abs=1e-7)


def test_risk_limit_is_after_fees_and_reversal_cannot_retain_old_sign():
    model = policy([[0.04]], gamma=100, limits=PortfolioLimits(3, 0.1))
    weights, diagnostics = model(
        0, np.array([0.5]), np.array([-1.0]), LinearBpsCost(1.5), np.array([False])
    )
    expected = -0.1 * (1 - 0.00015 * 0.5) / (0.2 + 0.1 * 0.00015)
    assert weights[0] == pytest.approx(expected, abs=1e-7)
    assert diagnostics["forecast_after_cost"] == pytest.approx(0.1, abs=1e-7)


def test_correlated_solution_matches_interior_analytic_gradient():
    covariance = np.array([[0.04, 0.02], [0.02, 0.09]])
    target = np.array([0.5, 0.4])
    model = policy(covariance)
    weights, _ = model(0, np.zeros(2), target, LinearBpsCost(1.5), np.zeros(2, bool))
    expected = target - np.linalg.solve(covariance, np.full(2, 12 * 0.00015 / 10))
    np.testing.assert_allclose(weights, expected, atol=1e-7)


def test_flat_month_closes_without_solver_and_preserves_inputs():
    model = policy(np.zeros((2, 2)))
    previous, target = np.array([0.4, -0.2]), np.zeros(2)
    weights, diagnostics = model(0, previous, target, LinearBpsCost(1.5), np.ones(2, bool))
    np.testing.assert_array_equal(weights, target)
    np.testing.assert_array_equal(previous, [0.4, -0.2])
    assert model.solve_count == 0
    assert diagnostics["tracking_objective"] == pytest.approx(0.00015 * 0.6)


def test_factor_reuse_and_zero_cost_target():
    cache = {}
    matrix = np.diag([0.04, 0.09])
    first, second = policy(matrix, factor_cache=cache), policy(matrix, gamma=20, factor_cache=cache)
    target = np.array([0.5, -0.4])
    for model in [first, second]:
        weights, _ = model(0, np.zeros(2), target, LinearBpsCost(0), np.zeros(2, bool))
        np.testing.assert_allclose(weights, target, atol=1e-6)
    assert len(cache) == 1
    assert next(iter(first.problems.values()))[0].is_dcp(dpp=True)


@pytest.mark.parametrize("bad", ["nan", "asymmetric", "indefinite", "cost", "roll", "insolvent"])
def test_unsupported_or_invalid_inputs_fail(bad):
    matrix, previous, target = np.eye(2), np.zeros(2), np.ones(2)
    cost, roll = LinearBpsCost(1.5), None
    if bad == "nan":
        target[0] = np.nan
    elif bad == "asymmetric":
        matrix[0, 1] = 0.2
    elif bad == "indefinite":
        matrix[0, 0] = -1
    elif bad == "cost":
        cost = ZeroCost()
    elif bad == "roll":
        roll = object()
    else:
        previous[:] = 10000
    with pytest.raises(ValueError):
        policy(matrix)(0, previous, target, cost, np.zeros(2, bool), roll_charge=roll)


def test_solver_failure_is_not_silently_replaced():
    model = policy(np.eye(2), settings=SolverSettings(max_iterations=1))
    with pytest.warns(UserWarning, match="inaccurate"), pytest.raises(
        ValueError, match="optimization failed"
    ):
        model(0, np.zeros(2), np.ones(2), LinearBpsCost(1.5), np.zeros(2, bool))


def test_independent_validation_rejects_bad_solver_answer(monkeypatch):
    model = policy([[0.04]])
    monkeypatch.setattr(model, "_solve", lambda *args: (np.array([-0.1]), {}))
    with pytest.raises(ValueError, match="feasibility"):
        model(0, np.zeros(1), np.ones(1), LinearBpsCost(1.5), np.zeros(1, bool))


def test_cost_matches_actual_trades_with_mixed_switches_and_exits():
    model = policy(np.diag([0.04, 0.09, 0.16]))
    previous, target = np.array([0.3, -0.2, 0.1]), np.array([0.4, -0.3, 0])
    switches = np.array([True, False, True])
    weights, diagnostic = model(0, previous, target, LinearBpsCost(1.5), switches)
    fee = 0.00015 * (abs(weights[0]) + 0.3 + abs(weights[1] + 0.2) + 0.1)
    assert LinearBpsCost(1.5).cost(traded_exposure(weights, previous, switches)[0]) == pytest.approx(fee)
    assert diagnostic["gross_after_cost"] == pytest.approx(np.abs(weights).sum() / (1 - fee))
