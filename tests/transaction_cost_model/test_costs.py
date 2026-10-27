import numpy as np
import pytest

from src.transaction_cost_model import LinearBpsCost, ZeroCost


@pytest.mark.parametrize("bps, expected", [(1, 0.000075), (2, 0.00015), (10, 0.00075)])
def test_linear_cost_is_bps_of_traded_exposure_and_splits_by_market(bps, expected):
    traded = np.array([0.5, 0.25])
    model = LinearBpsCost(bps)
    assert model.cost(traded) == pytest.approx(expected)
    np.testing.assert_allclose(model.instrument_cost(traded), traded * bps / 10000)
    assert model.instrument_cost(traded).sum() == pytest.approx(model.cost(traded))


def test_zero_cost_charges_nothing():
    traded = np.array([1.0, 2.0])
    assert ZeroCost().cost(traded) == 0
    assert not ZeroCost().instrument_cost(traded).any()


def test_negative_cost_is_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        LinearBpsCost(-1)
