import numpy as np
import pandas as pd
import pytest

from src.alpha_model import AlwaysLongSignal, CompoundedReturnSignal, SumReturnSignal
from src.backtest.engine import simulate
from src.models import MarketData
from src.portfolio_construction import InverseVolatilitySizer, PortfolioLimits, construct_targets
from src.risk_model import EwmaVolatilityRiskModel, RollingCovarianceRiskModel
from src.transaction_cost_model import ZeroCost

NO_LIMITS = PortfolioLimits(gross_cap=np.inf, risk_ceiling=np.inf)


def market(days=1800, seed=8):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2004-01-01", periods=days)
    prices = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.01, (days, 3)), axis=0),
        index=index,
        columns=list("ABC"),
    )
    month_end = prices.groupby(prices.index.to_period("M")).last()
    returns = month_end.pct_change().iloc[1:]
    meta = pd.DataFrame({"AssetClass": ["EQ", "FI", "FX"]}, index=prices.columns)
    return MarketData(returns, meta, prices)


def test_paper_pipeline_uses_the_same_interfaces_and_matches_hand_sizing():
    data = market()
    lag = 1
    sizer = InverseVolatilitySizer(scale=0.4, volatility_floor=0.0, minimum_instruments=2)
    risk = EwmaVolatilityRiskModel(lag=lag)
    targets, _, _ = construct_targets(
        data,
        {"trend": CompoundedReturnSignal(12)},
        risk,
        sizer,
        NO_LIMITS,
        lag=lag,
        start="2008-01",
        end="2010-12",
    )
    month = pd.Period("2009-06", "M")
    vol = risk.volatility(data).loc[month]
    sign = np.sign((1 + data.returns).rolling(12).apply(np.prod, raw=True) - 1).shift(lag)
    expected = sign.loc[month] * 0.4 / vol / 3
    np.testing.assert_allclose(targets["trend"].loc[month].to_numpy(), expected.to_numpy())
    ledger, _ = simulate(data.returns.loc["2008-01":"2010-12"], targets["trend"], ZeroCost())
    assert (ledger.cost == 0).all()
    np.testing.assert_allclose(ledger.net_return, ledger.gross_return)


def test_strategies_with_different_eligibility_are_rejected():
    data = market()
    sizer = InverseVolatilitySizer(scale=0.4, volatility_floor=0.0, minimum_instruments=2)
    risk = RollingCovarianceRiskModel(24, 1, 0.0, 0.5)
    with pytest.raises(ValueError, match="share one eligibility"):
        construct_targets(
            data,
            {"short": SumReturnSignal(6), "long": AlwaysLongSignal(36)},
            risk,
            sizer,
            NO_LIMITS,
            lag=1,
            start="2008-01",
            end="2010-12",
        )
