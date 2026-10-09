"""Monthly price-return proxy backtest with explicit timing and accounting."""

import numpy as np
import pandas as pd
import statsmodels.api as sm


def weights_and_signals(returns, meta, config):
    lag = config["information_lag_months"]
    if lag < 1:
        raise ValueError("Information lag must be at least one month")
    lookback, risk = config["signal_months"], config["volatility_months"]
    signal = np.sign(returns.rolling(lookback, min_periods=lookback).sum()).shift(lag)
    vol = returns.rolling(risk, min_periods=risk).std(ddof=1).mul(np.sqrt(12)).shift(lag)
    eligible = signal.notna() & vol.notna() & vol.gt(0)
    for asset in config["exclude_from_strategy"]:
        if asset in eligible:
            eligible[asset] = False
    inverse = (1 / vol.clip(lower=config["volatility_floor_annual"])).where(eligible, 0.0)
    count = eligible.sum(axis=1)
    # 40% is an instrument scale, not a portfolio volatility target.
    magnitude = (
        inverse.mul(config["instrument_volatility_scale"])
        .div(count.replace(0, np.nan), axis=0)
        .fillna(0.0)
    )
    magnitude.loc[count < config["minimum_instruments"]] = 0.0
    trend = magnitude * signal.fillna(0)
    return {"trend": trend, "static": magnitude, "eligible": eligible, "signal": signal, "vol": vol}


def traded_exposure(weights, previous, switched=None):
    traded = np.abs(weights - previous)
    extra = 0.0
    if switched is not None and switched.any():
        expanded = np.abs(weights[switched]) + np.abs(previous[switched])
        extra = float((expanded - traded[switched]).sum())
        traded[switched] = expanded
    return traded, extra


def simulate(
    returns,
    targets,
    cost_bps,
    source=None,
    risk_free=None,
    liquidate=True,
    position_policy=None,
    source_known_at=None,
    instrument_details=None,
):
    """Exposure in units of beginning-month NAV; futures collateral earns RF.

    Target exposures trade at the beginning endpoint (idealized). Units remain
    fixed during the month. Drifted end notionals are carried to next rebalance.
    Missing returns on held assets raise instead of becoming zero P&L.
    """
    assert targets.index.equals(returns.index) and targets.columns.equals(returns.columns)
    if source is not None and (
        not source.index.equals(returns.index) or not source.columns.equals(returns.columns)
    ):
        raise ValueError("Source schedule must match the return index and column order")
    if not np.isfinite(targets.to_numpy()).all():
        raise ValueError("Nonfinite target exposure")
    if cost_bps < 0:
        raise ValueError("Trading costs must be nonnegative")
    if source is not None and position_policy is not None:
        if source_known_at is None:
            raise ValueError("Policy-aware source costs require source_known_at dates")
        known = pd.to_datetime(source_known_at.reindex(returns.index))
        if (
            known.isna().any()
            or (known.to_numpy() >= returns.index.to_timestamp().to_numpy()).any()
        ):
            raise ValueError("Source schedule must be known before each return month")
    rate = cost_bps / 10000
    cash_rates = (
        pd.Series(0.0, index=returns.index)
        if risk_free is None
        else risk_free.reindex(returns.index)
    )
    if cash_rates.isna().any():
        raise ValueError("Missing collateral rate")
    previous = np.zeros(len(returns.columns))
    nav = 1.0
    prior_source = None
    rows, contributions, instrument_costs, holdings = [], [], [], []
    for i, month in enumerate(returns.index):
        w = targets.loc[month].to_numpy(dtype=float)
        switched = np.zeros(len(w), dtype=bool)
        if source is not None:
            current_source = source.loc[month].fillna("").to_numpy()
            if prior_source is not None:
                switched = (
                    (current_source != prior_source) & (current_source != "") & (prior_source != "")
                )
            prior_source = current_source
        diagnostics = {}
        if position_policy is not None:
            # The policy sees past holdings and current targets, never this month's return.
            w, diagnostics = position_policy(month, previous.copy(), w.copy(), rate, switched)
            if not np.isfinite(w).all():
                raise ValueError("Nonfinite executed exposure")
        r = returns.loc[month].to_numpy(dtype=float)
        missing_held = ~np.isfinite(r) & (np.abs(w) > 1e-14)
        if missing_held.any():
            raise ValueError(
                f"Missing held return at {month}: {list(returns.columns[missing_held])}"
            )
        # Only unheld observations may be ignored in P&L.
        r = np.where(np.isfinite(r), r, 0.0)
        traded, source_extra = traded_exposure(w, previous, switched)
        turnover = float(traded.sum())
        entry_cost = rate * turnover
        gross = float(w @ r)
        funding = float(cash_rates.loc[month]) * (1 - entry_cost)
        terminal_turnover = (
            float(np.abs(w * (1 + r)).sum()) if liquidate and i == len(returns) - 1 else 0.0
        )
        exit_cost = rate * terminal_turnover
        net = gross + funding - entry_cost - exit_cost
        if not np.isfinite(net) or 1 + net <= 0:
            raise ValueError(f"Nonfinite P&L or insolvent proxy account at {month}")
        ending_nav = nav * (1 + net)
        rows.append(
            dict(
                month=month,
                nav_start=nav,
                nav_end=ending_nav,
                gross_return=gross,
                collateral_income=funding,
                rebalance_cost=entry_cost,
                liquidation_cost=exit_cost,
                cost=entry_cost + exit_cost,
                net_return=net,
                turnover=turnover + terminal_turnover,
                rebalance_turnover=turnover,
                source_switch_extra_turnover=source_extra,
                terminal_turnover=terminal_turnover,
                gross_exposure=float(np.abs(w).sum()),
                net_exposure=float(w.sum()),
                held_instruments=int((np.abs(w) > 1e-14).sum()),
                cost_cash=nav * (entry_cost + exit_cost),
                rebalance_instruments=int((traded > 1e-12).sum()),
                end_gross_before_liquidation=float(
                    np.abs(w * (1 + r)).sum() / (1 + gross + funding - entry_cost)
                ),
                **diagnostics,
            )
        )
        contributions.append(w * r)
        # Allocate both source close/open trades and liquidation to the actual instrument.
        terminal_trades = (
            np.abs(w * (1 + r)) if liquidate and i == len(returns) - 1 else np.zeros(len(w))
        )
        instrument_costs.append(rate * (traded + terminal_trades))
        holdings.append(w.copy())
        previous = np.zeros(len(w)) if terminal_turnover else w * (1 + r) / (1 + net)
        nav = ending_nav
    ledger = pd.DataFrame(rows).set_index("month")
    attribution = pd.DataFrame(contributions, index=returns.index, columns=returns.columns)
    assert np.allclose(attribution.sum(axis=1), ledger.gross_return)
    assert np.allclose(ledger.nav_end, (1 + ledger.net_return).cumprod())
    assert np.allclose(
        ledger.net_return, ledger.gross_return + ledger.collateral_income - ledger.cost
    )
    if instrument_details is not None:
        instrument_details["cost"] = pd.DataFrame(
            instrument_costs, index=returns.index, columns=returns.columns
        )
        instrument_details["exposure"] = pd.DataFrame(
            holdings, index=returns.index, columns=returns.columns
        )
        assert np.allclose(instrument_details["cost"].sum(axis=1), ledger.cost)
    return ledger, attribution


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
        "turnover_ann": ledger.turnover.mean() * 12,
        "mean_cost_ann": ledger.cost.mean() * 12,
        "cost_cash_per_initial_capital": ledger.cost_cash.sum(),
        "avg_gross_exposure": ledger.gross_exposure.mean(),
    }


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
