"""Performance statistics and factor regressions on backtest ledgers."""

import numpy as np
import pandas as pd
import statsmodels.api as sm


def sharpe_ratio(net_returns, risk_free=None):
    """Annualized monthly mean/std; funded returns subtract matching monthly RF once."""
    excess = net_returns.copy()
    if risk_free is not None:
        rates = risk_free.reindex(excess.index)
        if rates.isna().any():
            raise ValueError("Missing matching risk-free return")
        excess = excess - rates
    volatility = excess.std(ddof=1) * np.sqrt(12)
    return excess.mean() * 12 / volatility if volatility > 0 else np.nan


def performance(ledger, risk_free=None):
    r = ledger.net_return
    wealth = (1 + r).cumprod()
    drawdown = wealth / wealth.cummax().clip(lower=1) - 1
    vol = r.std(ddof=1) * np.sqrt(12)
    return {
        "months": len(r),
        "mean_monthly": r.mean(),
        "std_monthly": r.std(ddof=1),
        "mean_ann": r.mean() * 12,
        "vol_ann": vol,
        "zero_rate_mean_vol_ratio": r.mean() * 12 / vol if vol else np.nan,
        "sharpe": sharpe_ratio(r, risk_free),
        "cagr": wealth.iloc[-1] ** (12 / len(r)) - 1,
        "cumulative_return": wealth.iloc[-1] - 1,
        "max_drawdown": drawdown.min(),
        "worst_month": r.min(),
        "best_month": r.max(),
        "hit_rate_monthly": (r > 0).mean(),
        "turnover_ann": ledger.turnover.mean() * 12,
        "mean_cost_ann": ledger.cost.mean() * 12,
        "cost_cash_per_initial_capital": ledger.cost_cash.sum(),
        "avg_gross_exposure": ledger.gross_exposure.mean(),
    }


def signal_hit_rate(attribution):
    """Share of held market-months whose position earned a positive P&L contribution."""
    held = attribution.ne(0) & attribution.notna()
    return (attribution.gt(0) & held).to_numpy().sum() / held.to_numpy().sum()


def regression_alpha(y, factors, lags):
    matched = pd.concat([y.rename("response"), factors], axis=1).dropna()
    x = sm.add_constant(matched.drop(columns="response"), has_constant="add")
    if len(matched) <= x.shape[1] + lags:
        raise ValueError("Insufficient matched data for regression")
    if np.linalg.matrix_rank(x) != x.shape[1]:
        raise ValueError("Rank deficient regression")
    fit = sm.OLS(matched.response, x).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True}, use_t=True
    )
    ci = fit.conf_int(alpha=0.05).loc["const"]
    row = {
        "months": len(matched),
        "hac_lags": lags,
        "alpha_monthly": fit.params["const"],
        "alpha_ann": 12 * fit.params["const"],
        "alpha_se_ann": 12 * fit.bse["const"],
        "alpha_ci_low_ann": 12 * ci.iloc[0],
        "alpha_ci_high_ann": 12 * ci.iloc[1],
        "alpha_t": fit.tvalues["const"],
        "alpha_p": fit.pvalues["const"],
        "r_squared": fit.rsquared,
    }
    for name in factors:
        row[f"beta_{name}"] = fit.params[name]
    return row, fit
