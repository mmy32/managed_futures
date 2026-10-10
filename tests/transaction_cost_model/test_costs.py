import numpy as np
import pytest

from src.transaction_cost_model import LinearBpsCost, ZeroCost


def test_linear_cost_is_bps_of_traded_exposure_and_splits_by_market():
    traded = np.array([0.5, 0.25])
    model = LinearBpsCost(10)
    assert model.cost(traded) == pytest.approx(0.00075)
    np.testing.assert_allclose(model.instrument_cost(traded), [0.0005, 0.00025])
    assert model.instrument_cost(traded).sum() == pytest.approx(model.cost(traded))


def test_zero_cost_charges_nothing():
    traded = np.array([1.0, 2.0])
    assert ZeroCost().cost(traded) == 0
    assert not ZeroCost().instrument_cost(traded).any()


def test_negative_cost_is_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        LinearBpsCost(-1)
