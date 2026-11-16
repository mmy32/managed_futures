"""Checks for matched eligibility, continuous period scoring and exported accounting."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import simulate
from src.backtest.monthly_runner import (
    CommonEligibilityRiskModel,
    independent_case_check,
    period_metrics,
)
from src.models import MarketData
from src.transaction_cost_model import LinearBpsCost


def fixture():
    index = pd.period_range("2000-01", "2002-12", freq="M")
    values = 0.01 + 0.02*np.sin(np.arange(len(index)))
    returns = pd.DataFrame({"A": values, "B": -values/2}, index=index)
    targets = pd.DataFrame({"A": 0.2, "B": -0.1}, index=index)
    details = {}
    ledger, _ = simulate(returns, targets, LinearBpsCost(2), instrument_details=details)
    matrices = np.tile(np.eye(2)*0.01, (len(index), 1, 1))
    spec = {"start": "2000-01", "development_end": "2001-12", "end": "2002-12",
                "cost_bps": 2, "gross_cap": 3, "portfolio_risk_ceiling": 0.1}
    return returns, ledger, details["exposure"], matrices, spec


def test_independent_accounting_checks_drift_entry_and_terminal_costs():
    returns, ledger, exposure, matrices, spec = fixture()
    independent_case_check(ledger, exposure, returns, matrices, spec)
    assert ledger.iloc[0].rebalance_cost > 0
    assert ledger.iloc[-1].liquidation_cost > 0


@pytest.mark.parametrize("defect", ["return", "cost", "holdings", "calendar", "risk"])
def test_independent_accounting_rejects_corrupted_exports(defect):
    returns, ledger, exposure, matrices, spec = fixture()
    if defect == "return":
        returns.iloc[12, 0] = np.nan
    elif defect == "cost":
        ledger.iloc[12, ledger.columns.get_loc("cost")] += 0.001
    elif defect == "holdings":
        exposure.iloc[12, 0] += 0.05
    elif defect == "calendar":
        ledger = ledger.iloc[1:]
    else:
        matrices *= 1000
    with pytest.raises((ValueError, AssertionError)):
        independent_case_check(ledger, exposure, returns, matrices, spec)


def test_period_metrics_keep_boundary_holdings_and_do_not_add_liquidation():
    _, ledger, _, _, spec = fixture()
    rows = {row["period"]: row for row in period_metrics(ledger, "rolling", "inverse_vol", spec)}
    assert [rows[key]["months"] for key in ("in_sample", "test_period", "full_sample")] == [24, 12, 36]
    assert ledger.loc["2001-12", "liquidation_cost"] == 0
    assert ledger.loc["2002-01", "nav_start"] != 1
    net = ledger.net_return
    np.testing.assert_allclose(
        (1+rows["in_sample"]["cumulative_return"])*(1+rows["test_period"]["cumulative_return"]),
        (1+net).prod(),
    )


def test_common_eligibility_masks_volatility_and_rejects_different_covariance_universe():
    returns, _, _, _, _ = fixture()

    class FixedRisk:
        def volatility(self, data):
            return data.returns*0+0.2

        def covariances(self, data, eligible):
            return {}, {}

    common = returns.notna()
    common.loc[common.index[:3], "B"] = False
    model = CommonEligibilityRiskModel(FixedRisk(), common)
    data = MarketData(returns, pd.DataFrame({"AssetClass": ["EQ", "FI"]}, index=returns.columns))
    assert model.volatility(data).iloc[:3].B.isna().all()
    model.covariances(data, common)
    with pytest.raises(ValueError, match="eligibility differs"):
        model.covariances(data, returns.notna())
