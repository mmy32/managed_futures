"""Past-eligible descriptive portfolios and calendar-aware sample diagnostics."""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import t as student_t

from src.backtest.attribution import CLASS_NAMES
from src.backtest.performance import performance, sharpe_ratio
from src.backtest.research_spec import primary_key


def sample_audit(returns, eligible, base):
    """Never advance the requested start or lower the instrument threshold."""
    expected = pd.period_range(base["start"], base["end"], freq="M")
    if not expected.isin(returns.index).all():
        raise ValueError("Requested sample has missing calendar months")
    first = expected[0]
    counts = eligible.loc[expected].sum(axis=1)
    active = counts >= base["minimum_instruments"]
    return {
        "start": str(first),
        "end": str(expected[-1]),
        "months": len(expected),
        "initialization_start": str(returns.index.min()),
        "prior_risk_window_start": str(first - base["volatility_months"]),
        "prior_risk_window_end": str(first - 1),
        "eligible_at_start": int(counts.iloc[0]),
        "minimum_required": base["minimum_instruments"],
        "start_ready": bool(active.iloc[0]),
        "below_minimum_months": int((~active).sum()),
        "first_investable_month": str(counts.index[active][0]) if active.any() else None,
        "treatment": "Requested dates retained; existing minimum-instrument rule leaves portfolios flat below threshold.",
    }


def class_portfolios(returns, eligible, meta, index):
    """Average only prior-eligible assets; absent classes stay missing, never cash-filled."""
    sample = returns.loc[index]
    allowed = eligible.loc[index]
    series, counts, rows = {}, {}, []
    for group, name in CLASS_NAMES.items():
        assets = meta.reindex(sample.columns).index[
            meta.reindex(sample.columns).AssetClass.eq(group)
        ]
        selected = allowed[assets]
        count = selected.sum(axis=1)
        s = sample[assets].where(selected).sum(axis=1, min_count=1).div(count.replace(0, np.nan))
        missing_selected = selected & ~np.isfinite(sample[assets])
        # An unknown constituent return makes the whole class return unknown.
        # Never drop it from the denominator or turn its P&L into zero.
        s = s.mask(missing_selected.any(axis=1))
        series[group], counts[group] = s, count
        valid = s.dropna()
        rows.append(
            {
                "asset_class": group,
                "name": name,
                "instruments": int(selected.any().sum()),
                "instrument_observations": int((selected & sample[assets].notna()).sum().sum()),
                "missing_eligible_observations": int(missing_selected.sum().sum()),
                "months": int(s.count()),
                "first_month": str(valid.index.min()),
                "last_month": str(valid.index.max()),
                "minimum_eligible": int(count.min()),
                "maximum_eligible": int(count.max()),
                "mean_monthly": s.mean(),
                "std_monthly": s.std(ddof=1),
                "mean_ann": s.mean() * 12,
                "vol_ann": s.std(ddof=1) * np.sqrt(12),
                "sharpe": sharpe_ratio(s),
            }
        )
    return pd.DataFrame(series), pd.DataFrame(counts), pd.DataFrame(rows)


def rank_autocorrelation(series, lags=range(1, 13)):
    """Pairwise Spearman with HAC scores on the intact calendar (missing scores zero).

    For lag k, use k Bartlett/Newey-West lags, n/(n-2) correction and a
    t(n-2) interval for the standardized-rank OLS slope. These are exploratory.
    """
    expected = pd.period_range(series.index.min(), series.index.max(), freq="M")
    if not series.index.equals(expected):
        raise ValueError("Autocorrelation requires the intact monthly calendar")
    rows = []
    for group, s in series.items():
        for lag in lags:
            pairs = pd.concat([s.rename("current"), s.shift(lag).rename("lagged")], axis=1).dropna()
            n = len(pairs)
            result = {
                "asset_class": group,
                "lag": lag,
                "matched_months": n,
                "hac_lags": lag,
                "rho": np.nan,
                "se": np.nan,
                "ci_low": np.nan,
                "ci_high": np.nan,
                "p_approx": np.nan,
            }
            if n > lag + 2 and pairs.nunique().min() > 1:
                ranks = pairs.rank(method="average")
                z = (ranks - ranks.mean()) / ranks.std(ddof=1)
                x = np.column_stack([np.ones(n), z.lagged.to_numpy()])
                fit = sm.OLS(z.current, x).fit()
                scores = (
                    pd.DataFrame(x * fit.resid.to_numpy()[:, None], index=pairs.index)
                    .reindex(series.index, fill_value=0.0)
                    .to_numpy()
                )
                meat = scores.T @ scores
                for h in range(1, lag + 1):
                    cross = scores[h:].T @ scores[:-h]
                    meat += (1 - h / (lag + 1)) * (cross + cross.T)
                bread = np.linalg.inv(x.T @ x)
                covariance = bread @ meat @ bread * n / (n - 2)
                se = np.sqrt(max(covariance[1, 1], 0.0))
                rho = float(fit.params.iloc[1])
                critical = student_t.ppf(0.975, n - 2)
                result.update(
                    rho=rho,
                    se=se,
                    ci_low=rho - critical * se,
                    ci_high=rho + critical * se,
                    p_approx=float(2 * student_t.sf(abs(rho / se), n - 2)) if se > 0 else np.nan,
                )
            rows.append(result)
    return pd.DataFrame(rows)


def risk_diagnostics(ledger):
    forecast = ledger.forecast_vol_annual
    valid = forecast > 1e-12
    standardized = ledger.loc[valid, "gross_return"] / (forecast[valid] / np.sqrt(12))
    wealth = ledger.nav_end
    through_time = pd.DataFrame(
        {
            "realized_net_vol_36m": ledger.net_return.rolling(36).std(ddof=1) * np.sqrt(12),
            "realized_gross_vol_36m": ledger.gross_return.rolling(36).std(ddof=1) * np.sqrt(12),
            "forecast_rms_36m": forecast.pow(2).rolling(36).mean().pow(0.5),
            "gross_after_cost": ledger.gross_after_cost,
            "drawdown": wealth / wealth.cummax().clip(lower=1) - 1,
        }
    )
    summary = {
        "realized_predicted_ratio": standardized.std(ddof=1),
        "rms_forecast_vol": np.sqrt(forecast.pow(2).mean()),
        "calibration_months": int(valid.sum()),
    }
    return through_time, summary


def stability_summary(ledgers, settings):
    """Descriptive blocks of the existing trading path; no new strategies or holdouts."""
    rows = []
    fields = ["months", "mean_ann", "cagr", "vol_ann", "sharpe", "max_drawdown"]
    for strategy in ["trend", "static"]:
        ledger = ledgers[primary_key(settings, strategy)]
        for start, end in [
            ("1976", "1984"),
            ("1985", "1994"),
            ("1995", "2004"),
            ("2005", "2014"),
            ("2008", "2008"),
        ]:
            block = ledger.loc[start:end]
            stats = performance(block)
            rows.append(
                dict(
                    strategy=strategy,
                    period=start if start == end else f"{start}–{end}",
                    **{field: stats[field] for field in fields},
                )
            )
        # Noncontiguous observations support mean/SD only, not a tradable NAV/drawdown.
        returns = ledger.loc[ledger.index.year != 2008, "net_return"]
        rows.append(
            {
                "strategy": strategy,
                "period": "Excluding 2008 (noncontiguous)",
                "months": len(returns),
                "mean_ann": returns.mean() * 12,
                "vol_ann": returns.std(ddof=1) * np.sqrt(12),
                "sharpe": sharpe_ratio(returns),
                "cagr": np.nan,
                "max_drawdown": np.nan,
            }
        )
    return pd.DataFrame(rows).assign(
        model=settings["primary_model"],
        band=settings["primary_band"],
        cost_bps=settings["primary_cost_bps"],
    )
