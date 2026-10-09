"""Lagged covariance forecasts and stateful no-trade bands for research portfolios."""

import copy

import numpy as np
import pandas as pd

from src.backtest.engine import traded_exposure, weights_and_signals


def portfolio_risk(weights, covariance):
    variance = float(weights @ covariance @ weights)
    if variance < -1e-10 or not np.isfinite(variance):
        raise ValueError("Invalid forecast variance")
    return np.sqrt(max(variance, 0.0))


def bounded_target(weights, covariance, gross_cap, risk_ceiling):
    gross, risk = np.abs(weights).sum(), portfolio_risk(weights, covariance)
    scale = min(1.0, gross_cap / gross if gross else 1.0, risk_ceiling / risk if risk else 1.0)
    return weights * scale


def build_forecasts(returns, meta, base, settings, model="correlated"):
    if not isinstance(returns.index, pd.PeriodIndex) or not returns.index.equals(
        pd.period_range(returns.index.min(), returns.index.max(), freq="M")
    ):
        raise ValueError("Risk inputs must have a unique, ordered, complete monthly calendar")
    if not isinstance(base["information_lag_months"], int) or base["information_lag_months"] < 1:
        raise ValueError("Risk forecasts require an integer information lag of at least one month")
    if model not in ["diagonal", "correlated", "class_balanced"]:
        raise ValueError("Unknown risk model")
    if not 0 < settings["correlation_shrinkage"] <= 1:
        raise ValueError("Shrinkage must be positive and at most one")
    cfg = copy.deepcopy(base)
    cfg["volatility_months"] = settings["volatility_months"]
    cfg["volatility_floor_annual"] = settings["volatility_floor_annual"]
    w = weights_and_signals(returns, meta, cfg)
    index = returns.loc[cfg["start"] : cfg["end"]].index
    targets = {
        k: pd.DataFrame(0.0, index=index, columns=returns.columns) for k in ["trend", "static"]
    }
    covariance, records = {}, []
    labels = meta.reindex(returns.columns).AssetClass.to_numpy()
    for month in index:
        active = w["eligible"].loc[month].to_numpy()
        ids = np.flatnonzero(active)
        matrix = np.zeros((returns.shape[1], returns.shape[1]))
        # Lag=1: endpoint t-1 is the latest input, even when t's return is missing.
        end = returns.index.get_loc(month) - cfg["information_lag_months"] + 1
        hist = returns.iloc[end - cfg["volatility_months"] : end, ids]
        if len(ids):
            if len(hist) != cfg["volatility_months"] or hist.isna().any().any():
                raise ValueError("Incomplete common estimation window")
            vol = hist.std(ddof=1).to_numpy() * np.sqrt(12)
            floor_vol = np.maximum(vol, cfg["volatility_floor_annual"])
            if model == "diagonal":
                correlation = np.eye(len(ids))
            else:
                sample = hist.corr().to_numpy()
                shrinkage = settings["correlation_shrinkage"]
                correlation = (1 - shrinkage) * sample + shrinkage * np.eye(len(ids))
            small = correlation * np.outer(floor_vol, floor_vol)
            assert np.isfinite(small).all() and np.allclose(small, small.T)
            eigenvalue = float(np.linalg.eigvalsh(small).min())
            if eigenvalue <= 0:
                raise ValueError("Forecast covariance is not positive definite on eligible assets")
            matrix[np.ix_(ids, ids)] = small
        else:
            eigenvalue = np.nan
        covariance[month] = matrix
        for strategy, target in targets.items():
            raw = w[strategy].loc[month].to_numpy().copy()
            if model == "class_balanced" and len(ids) >= cfg["minimum_instruments"]:
                classes = sorted(set(labels[ids]))
                budget = settings["portfolio_risk_ceiling"] / np.sqrt(len(classes))
                for group in classes:
                    chosen = (labels == group) & active
                    component = np.where(chosen, raw, 0.0)
                    standalone = portfolio_risk(component, matrix)
                    if standalone > 0:
                        raw[chosen] *= budget / standalone
            desired = bounded_target(
                raw, matrix, settings["gross_cap"], settings["portfolio_risk_ceiling"]
            )
            target.loc[month] = desired
            records.append(
                {
                    "month": month,
                    "strategy": strategy,
                    "eligible": len(ids),
                    "information_through": month - cfg["information_lag_months"],
                    "estimation_start": month
                    - cfg["information_lag_months"]
                    - cfg["volatility_months"]
                    + 1,
                    "min_eigenvalue": eigenvalue,
                    "raw_gross": np.abs(raw).sum(),
                    "raw_forecast": portfolio_risk(raw, matrix),
                    "target_gross": np.abs(desired).sum(),
                    "target_forecast": portfolio_risk(desired, matrix),
                    "target_gross_limited": np.abs(raw).sum() > settings["gross_cap"] + 1e-12,
                    "target_risk_limited": portfolio_risk(raw, matrix)
                    > settings["portfolio_risk_ceiling"] + 1e-12,
                }
            )
    return targets, covariance, pd.DataFrame(records)


def band_positions(previous, target, band):
    if not 0 <= band < 1:
        raise ValueError("Band must lie in [0,1)")
    same_direction = previous * target > 0
    width = band * np.abs(target)
    # np.clip handles shorts too: e.g. target -2%, band [-2.2%,-1.8%].
    return np.where(same_direction, np.clip(previous, target - width, target + width), target)


def enforce_limits(proposed, previous, covariance, rate, switched, gross_cap, risk_ceiling):
    """Largest proportional holding reduction satisfying limits after entry fees."""
    gross = float(np.abs(proposed).sum())
    risk = portfolio_risk(proposed, covariance)
    load = max(gross / gross_cap, risk / risk_ceiling)

    def used_capital(scale):
        fee = rate * traded_exposure(scale * proposed, previous, switched)[0].sum()
        return scale * load + fee

    if used_capital(0.0) >= 1:
        raise ValueError("Insufficient capital to close positions")
    if used_capital(1.0) <= 1:
        return proposed.copy(), 1.0
    # Trading costs are piecewise linear; small proportional costs make this monotone.
    if rate * gross_cap >= 1:
        raise ValueError("Cost assumption incompatible with proportional limit solver")
    low, high = 0.0, 1.0
    for _ in range(50):
        middle = (low + high) / 2
        if used_capital(middle) <= 1:
            low = middle
        else:
            high = middle
    return proposed * low, low


class BandPolicy:
    def __init__(self, covariance, settings, band):
        self.covariance = covariance
        self.settings = settings
        self.band = band
        self.executed = {}
        self.proposed = {}

    def __call__(self, month, previous, target, rate, switched):
        matrix = self.covariance[month]
        proposal = band_positions(previous, target, self.band)
        selected, scale = enforce_limits(
            proposal,
            previous,
            matrix,
            rate,
            switched,
            self.settings["gross_cap"],
            self.settings["portfolio_risk_ceiling"],
        )
        trades, _ = traded_exposure(selected, previous, switched)
        fee = rate * trades.sum()
        forecast = portfolio_risk(selected, matrix)
        gross_after_cost = np.abs(selected).sum() / (1 - fee)
        risk_after_cost = forecast / (1 - fee)
        assert gross_after_cost <= self.settings["gross_cap"] + 1e-10
        assert risk_after_cost <= self.settings["portfolio_risk_ceiling"] + 1e-10
        self.executed[month] = selected.copy()
        self.proposed[month] = proposal.copy()
        proposal_fee = rate * traded_exposure(proposal, previous, switched)[0].sum()
        wanted = np.abs(target - previous) > 1e-12
        skipped = wanted & (np.abs(proposal - previous) <= 1e-12)
        return selected, {
            "forecast_vol_annual": forecast,
            "forecast_after_cost": risk_after_cost,
            "gross_after_cost": gross_after_cost,
            "gross_limit_breach": gross_after_cost > self.settings["gross_cap"] + 1e-10,
            "risk_limit_breach": risk_after_cost > self.settings["portfolio_risk_ceiling"] + 1e-10,
            "limit_override": scale < 1 - 1e-10,
            "gross_override": np.abs(proposal).sum()
            > self.settings["gross_cap"] * (1 - proposal_fee) + 1e-10,
            "risk_override": portfolio_risk(proposal, matrix)
            > self.settings["portfolio_risk_ceiling"] * (1 - proposal_fee) + 1e-10,
            "band_skipped_resizes": int(skipped.sum()),
            "net_skipped_resizes": int((skipped & (np.abs(selected - previous) <= 1e-12)).sum()),
            "target_distance_l1": float(np.abs(selected - target).sum()),
            "forecast_tracking_risk": portfolio_risk(selected - target, matrix),
            "drifted_gross_before": float(np.abs(previous).sum()),
        }
