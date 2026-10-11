"""Asset-class attribution of backtest P&L, exposure and forecast risk."""

import numpy as np
import pandas as pd

CLASS_NAMES = {"COMM": "Commodities", "EQ": "Equities", "FI": "Fixed income", "FX": "Currencies"}


def class_attribution(ledger, gross, details, covariance, meta):
    """Euler forecast-volatility contributions sum to portfolio forecast volatility."""
    labels = meta.reindex(gross.columns).AssetClass
    if not labels.isin(CLASS_NAMES).all():
        raise ValueError("Unmapped asset class")
    if not np.allclose(ledger.collateral_income, 0):
        raise ValueError("Class attribution requires zero-funded primary returns")
    net, exposure, risk = {}, {}, {}
    for group in CLASS_NAMES:
        chosen = labels.eq(group)
        net[group] = (gross.loc[:, chosen] - details["cost"].loc[:, chosen]).sum(axis=1)
        exposure[group] = details["exposure"].loc[:, chosen].abs().sum(axis=1)
        contributions = []
        for month, w in details["exposure"].iterrows():
            weights = w.to_numpy()
            marginal = covariance[month] @ weights
            vol = np.sqrt(max(float(weights @ marginal), 0.0))
            contributions.append(float((weights * marginal)[chosen].sum() / vol) if vol else 0.0)
        risk[group] = contributions
    net, exposure = pd.DataFrame(net), pd.DataFrame(exposure)
    risk = pd.DataFrame(risk, index=ledger.index)
    np.testing.assert_allclose(net.sum(axis=1), ledger.net_return, atol=1e-13)
    np.testing.assert_allclose(risk.sum(axis=1), ledger.forecast_vol_annual, atol=1e-13)
    # Wealth-linked contributions reconcile to compounded portfolio P&L as well.
    linked = net.mul(ledger.nav_start, axis=0).sum()
    np.testing.assert_allclose(linked.sum(), ledger.nav_end.iloc[-1] - 1, atol=1e-11)
    summary = pd.DataFrame(
        {
            "net_mean_ann": net.mean() * 12,
            "contribution_vol_ann": net.std(ddof=1) * np.sqrt(12),
            "avg_gross_exposure": exposure.mean(),
            "avg_forecast_vol_contribution": risk.mean(),
            "linked_cumulative_contribution": linked,
        }
    )
    summary.index.name = "asset_class"
    return net, exposure, risk, summary.reset_index()
