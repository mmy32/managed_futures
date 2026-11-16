"""Monthly GARCH/DCC: annual past-only fits and one-month covariance forecasts.

This is a monthly-frequency specification, not a daily model fed monthly observations.
Gaussian quasi-likelihood assumes zero conditional mean and targets each market's past
mean squared return. The variance forecast is annualized by 12 exactly once. Missing
estimation observations retain their calendar slots and use conditional moments; no
missing portfolio P&L is filled.
"""

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.config import MONTHS_PER_YEAR
from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar
from src.risk_model.daily import complete_monthly_window, shrunk_covariance
from src.risk_model.garch import (
    GarchParams,
    _checked_fit,
    _dcc_pair_negative_loglik,
    _pooled_negative_loglik,
    conditional_residual_moment,
    garch_variance,
    nearest_correlation,
)


def fit_monthly_garch(series, minimum, diagnostics):
    """Fit shared monthly alpha/beta, retaining missing slots in each market history."""
    if not series:
        raise ValueError("Monthly GARCH needs market histories")
    for values in series:
        observed = values[np.isfinite(values)]
        if (values.ndim != 1 or np.isinf(values).any() or len(observed) < minimum
                or not 0 < np.mean(observed**2) < np.inf):
            raise ValueError(f"Monthly GARCH requires {minimum} observed months and positive variance")
    result = minimize(
        _pooled_negative_loglik, x0=[0.97, 0.06], args=(series,),
        bounds=[(0.5, 0.9995), (0.005, 0.5)], method="L-BFGS-B",
    )
    persistence, share = _checked_fit(
        result, "Monthly GARCH",
        lambda x: 0.5 <= x[0] <= 0.9995 and 0.005 <= x[1] <= 0.5, diagnostics,
    )
    return GarchParams(persistence * share, persistence * (1 - share))


def monthly_pairs(z, minimum, count, rng):
    """Sample pairs using only the declared past residual panel and joint coverage."""
    if z.shape[1] < 2:
        raise ValueError("Monthly DCC needs at least two modelled markets")
    pairs = []
    for _ in range(20 * count):
        i, j = rng.choice(z.shape[1], size=2, replace=False)
        left, right = z.iloc[:, i].to_numpy(), z.iloc[:, j].to_numpy()
        observed = np.isfinite(left) & np.isfinite(right)
        if observed.sum() >= minimum:
            target = float(np.corrcoef(left[observed], right[observed])[0, 1])
            if np.isfinite(target) and abs(target) < 1:
                pairs.append((left, right, target))
        if len(pairs) == count:
            break
    if not pairs:
        raise ValueError("Monthly DCC has no sufficiently overlapping pair")
    return pairs


def fit_monthly_dcc(z, minimum, count, rng, diagnostics):
    pairs = monthly_pairs(z, minimum, count, rng)
    result = minimize(
        _dcc_pair_negative_loglik, x0=[0.02, 0.95], args=(pairs,), method="Nelder-Mead",
        options={"xatol": 1e-5, "fatol": 1e-8, "maxiter": 2000},
    )
    a, b = _checked_fit(result, "Monthly DCC", lambda x: x[0] >= 0 and x[1] >= 0
                        and x.sum() < 0.9999, diagnostics)
    diagnostics["pairs"] = len(pairs)
    return float(a), float(b)


@dataclass(frozen=True)
class MonthlyYearModel:
    variance: pd.DataFrame
    covariance: dict[pd.Period, pd.DataFrame]
    modelled: tuple[str, ...]


class MonthlyDccGarchRiskModel:
    """Pooled monthly GARCH(1,1), dynamic correlations, prior-December annual refits.

    The 36-month window governs current eligibility. Annual fitting additionally
    requires ``min_fit_observations`` actual monthly returns per market. Parameters,
    variance targets and correlation targets use expanding history ending before
    the forecast year. At lag two the prior year's December refit becomes usable
    in February; its January forecast therefore retains the older annual fit.
    """

    def __init__(
        self, asset_class: pd.Series, window: int = 36, lag: int = 1,
        volatility_floor: float = 0.02, correlation_shrinkage: float = 0.1,
        min_fit_observations: int = 60, pair_count: int = 100, seed: int = 0,
        forecast_start: str | None = "1976-01",
    ):
        if any(type(value) is not int or value < 1
               for value in (window, min_fit_observations, pair_count)):
            raise ValueError("Monthly GARCH window, fitting minimum and pair count must be positive integers")
        if min_fit_observations < 3 or not 0 < correlation_shrinkage <= 1:
            raise ValueError("Monthly GARCH needs at least three fitting months and valid shrinkage")
        if not np.isfinite(volatility_floor) or volatility_floor < 0:
            raise ValueError("Monthly GARCH volatility floor must be finite and nonnegative")
        if not asset_class.index.is_unique or asset_class.isna().any():
            raise ValueError("Monthly GARCH asset classes must be unique and observed")
        self.asset_class = asset_class.copy()
        self.window, self.lag = window, check_lag(lag)
        self.volatility_floor, self.correlation_shrinkage = volatility_floor, correlation_shrinkage
        self.minimum, self.pair_count, self.seed = min_fit_observations, pair_count, seed
        self.forecast_start = None if forecast_start is None else pd.Period(forecast_start, freq="M")
        self._returns: pd.DataFrame | None = None
        self._forecasts: dict[pd.Period, pd.DataFrame] = {}
        self._fits: dict[int, dict] = {}
        self._coverage: list[dict] = []

    def _universe(self, returns):
        eligible = complete_monthly_window(returns, self.window).shift(self.lag, fill_value=False)
        eligible.loc[:, ~eligible.columns.isin(self.asset_class.index)] = False
        if self.forecast_start is not None:
            eligible.loc[eligible.index < self.forecast_start] = False
        return eligible

    def _validate(self, data):
        returns = data.returns
        check_monthly_calendar(returns)
        if returns.empty or not returns.columns.is_unique or np.isinf(returns.to_numpy()).any():
            raise ValueError("Monthly GARCH requires nonempty unique markets and finite-or-missing returns")
        if self._returns is not None and not self._returns.equals(returns):
            raise ValueError("Monthly GARCH inputs changed; create a fresh model for another panel")
        return returns

    def _pooled_parameters(self, fit, modelled, year, diagnostics):
        params = {}
        for group in sorted(set(self.asset_class.reindex(modelled))):
            members = [name for name in modelled if self.asset_class[name] == group]
            record = {}
            try:
                values = [fit[name].to_numpy(float) for name in members]
                fitted = fit_monthly_garch(values, self.minimum, record)
            except ValueError as error:
                raise ValueError(f"Monthly GARCH refit {year}, class {group}: {error}") from error
            diagnostics.update({f"{group}_{key}": value for key, value in record.items()})
            diagnostics.update({f"{group}_alpha": fitted.alpha, f"{group}_beta": fitted.beta,
                                f"{group}_markets": len(members)})
            params.update({name: fitted for name in members})
        return params

    @staticmethod
    def _variance_paths(through, targets, params):
        variance, residuals = {}, {}
        for market in through:
            p, target = params[market], targets[market]
            values = through[market].to_numpy(float)
            h = garch_variance(values, target * (1-p.alpha-p.beta), p.alpha, p.beta, target)
            variance[market] = h[1:]
            residuals[market] = values / np.sqrt(h[:-1])
        return (pd.DataFrame(variance, index=through.index),
                pd.DataFrame(residuals, index=through.index))

    @staticmethod
    def _covariance_paths(z, variance, target, dcc):
        a, b = dcc
        q = target.copy()
        paths = {}
        for month, values in zip(z.index, z.to_numpy(), strict=True):
            q = (1-a-b)*target + a*conditional_residual_moment(values, q) + b*q
            sd = np.sqrt(variance.loc[month].to_numpy())
            scale = np.sqrt(np.diag(q))
            annual = q / np.outer(scale, scale) * np.outer(sd, sd) * MONTHS_PER_YEAR
            paths[month] = pd.DataFrame(annual, index=z.columns, columns=z.columns)
        return paths

    def _fit_year(self, returns, year):
        started = perf_counter()
        fit = returns.loc[:f"{year-1}-12", returns.columns.isin(self.asset_class.index)]
        targets = (fit**2).mean()
        modelled = list(fit.columns[(fit.notna().sum() >= self.minimum) & targets.gt(0)])
        if len(modelled) < 2:
            raise ValueError(f"Monthly GARCH refit {year} needs two markets with {self.minimum} observed months")
        diagnostics = {"year": year, "fit_information_through": f"{year-1}-12",
                       "fit_months": len(fit), "modelled_markets": len(modelled),
                       "minimum_observed_months": int(fit[modelled].count().min())}
        params = self._pooled_parameters(fit, modelled, year, diagnostics)
        through = returns.loc[:f"{year}-12", modelled]
        variance, z = self._variance_paths(through, targets, params)
        record = {}
        try:
            dcc = fit_monthly_dcc(z.loc[:f"{year-1}-12"], self.minimum, self.pair_count,
                                  np.random.default_rng(self.seed+year), record)
        except ValueError as error:
            raise ValueError(f"Monthly DCC refit {year}: {error}") from error
        diagnostics.update({f"dcc_{key}": value for key, value in record.items()})
        diagnostics.update(dcc_a=dcc[0], dcc_b=dcc[1])
        raw = z.loc[:f"{year-1}-12"].corr(min_periods=self.minimum).fillna(0).to_numpy().copy()
        np.fill_diagonal(raw, 1.0)
        paths = self._covariance_paths(z, variance, nearest_correlation(raw), dcc)
        diagnostics["fit_seconds"] = perf_counter()-started
        self._fits[year] = diagnostics
        return MonthlyYearModel(variance, paths, tuple(modelled))

    def _ensure(self, data):
        returns = self._validate(data)
        if self._returns is None:
            universe = self._universe(returns)
            active = universe.index[universe.any(axis=1)]
            years = {month: (month-self.lag+1).year for month in active}
            for year in sorted(set(years.values())):
                model = self._fit_year(returns, year)
                for month in active:
                    if years[month] == year:
                        self._forecasts[month] = model.covariance[month-self.lag]
            self._returns = returns.copy()
        return self._forecasts

    def volatility(self, data: MarketData) -> pd.DataFrame:
        forecasts = self._ensure(data)
        universe = self._universe(data.returns)
        vol = pd.DataFrame(np.nan, index=data.returns.index, columns=data.returns.columns)
        self._coverage = []
        for month, matrix in forecasts.items():
            markets = [name for name in matrix if universe.loc[month, name]]
            vol.loc[month, markets] = np.sqrt(np.diag(matrix.loc[markets, markets]))
            cutoff = month-self.lag
            history = data.returns.loc[:cutoff, markets]
            self._coverage.extend({"month": month, "market": name,
                                   "information_through": cutoff,
                                   "observed_months": int(history[name].count()),
                                   "missing_months": int(history[name].isna().sum())}
                                  for name in markets)
        return vol

    def covariances(self, data, eligible):
        forecasts = self._ensure(data)
        covariance, details = {}, {}
        for month in eligible.index:
            ids = np.flatnonzero(eligible.loc[month].to_numpy())
            matrix = np.zeros((data.returns.shape[1], data.returns.shape[1]))
            eigenvalue = np.nan
            if len(ids):
                markets = list(data.returns.columns[ids])
                raw = forecasts[month].loc[markets, markets].to_numpy()
                vol = np.sqrt(np.diag(raw))
                small = shrunk_covariance(vol, raw/np.outer(vol, vol), self.volatility_floor,
                                          self.correlation_shrinkage)
                matrix[np.ix_(ids, ids)] = small
                eigenvalue = float(np.linalg.eigvalsh(small).min())
            covariance[month] = matrix
            details[month] = {"information_through": month-self.lag, "estimation_start": pd.NaT,
                              "min_eigenvalue": eigenvalue}
        return covariance, details

    def fitted_parameters(self) -> pd.DataFrame:
        """Actual optimizer outcomes and monthly parameter estimates for each annual fit."""
        return pd.DataFrame([self._fits[year] for year in sorted(self._fits)])

    def coverage_diagnostics(self) -> pd.DataFrame:
        return pd.DataFrame(self._coverage)
