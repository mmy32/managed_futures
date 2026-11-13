"""DCC-GARCH covariance forecasts from daily returns (Engle 2002), refit each January.

Each market has a GARCH(1,1) variance with variance targeting. The (alpha, beta) pair is
pooled by asset class so markets with short histories get stable estimates. Correlations
follow DCC on the standardized residuals, with the two DCC parameters fitted by composite
likelihood on random pairs (Engle, Shephard and Sheppard 2008). Gaussian quasi-likelihood.
Forecasts for month t use daily returns through the end of month t - lag only. January
parameter refits use the prior December and become available after the configured lag.
"""

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter

from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar
from src.risk_model.daily import complete_monthly_window, shrunk_covariance, window_dates

HORIZON_DAYS = 21
MIN_FIT_OBS = 250
DCC_PAIRS = 100
DCC_WARMUP_DAYS = 1500
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class GarchParams:
    alpha: float
    beta: float


def garch_variance(
    returns: np.ndarray, omega: float, alpha: float, beta: float, start: float
) -> np.ndarray:
    """Conditional variances h[0..T]; h[t] uses returns before t, h[T] is the next-day forecast."""
    shocks = np.concatenate(([start], returns**2))
    h, _ = lfilter([1.0], [1.0, -beta], omega + alpha * shocks, zi=[beta * start])
    return h


def _pooled_negative_loglik(theta, series: list[np.ndarray]) -> float:
    persistence, share = theta
    alpha, beta = persistence * share, persistence * (1 - share)
    total, count = 0.0, 0
    for returns in series:
        target = float(np.mean(returns**2))
        h = garch_variance(returns, target * (1 - persistence), alpha, beta, target)[:-1]
        total += float(np.sum(np.log(h) + returns**2 / h))
        count += len(returns)
    return total / count


def fit_pooled_garch(series: list[np.ndarray]) -> GarchParams:
    """Common (alpha, beta) for several markets, each with its own long-run variance."""
    result = minimize(
        _pooled_negative_loglik,
        x0=[0.97, 0.06],
        args=(series,),
        bounds=[(0.5, 0.9995), (0.005, 0.5)],
        method="L-BFGS-B",
    )
    persistence, share = result.x
    return GarchParams(persistence * share, persistence * (1 - share))


def _dcc_pair_negative_loglik(theta, pairs: list[tuple[np.ndarray, np.ndarray, float]]) -> float:
    a, b = theta
    if a < 0 or b < 0 or a + b >= 0.9999:
        return 1e10
    total, count = 0.0, 0
    for zi, zj, target in pairs:
        decay = [1.0, -b]
        kept = 1 - a - b
        q_ii = lfilter([1.0], decay, kept + a * np.concatenate(([1.0], zi[:-1] ** 2)), zi=[b])[0]
        q_jj = lfilter([1.0], decay, kept + a * np.concatenate(([1.0], zj[:-1] ** 2)), zi=[b])[0]
        q_ij = lfilter(
            [1.0],
            decay,
            kept * target + a * np.concatenate(([target], zi[:-1] * zj[:-1])),
            zi=[b * target],
        )[0]
        rho = np.clip(q_ij / np.sqrt(q_ii * q_jj), -0.999, 0.999)
        total += float(
            np.sum(np.log(1 - rho**2) + (zi**2 + zj**2 - 2 * rho * zi * zj) / (1 - rho**2))
        )
        count += len(zi)
    return total / count


def fit_dcc(z: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float]:
    """DCC (a, b) from composite likelihood over random market pairs with enough overlap."""
    columns = list(z.columns)
    if len(columns) < 2:
        raise ValueError("DCC estimation requires at least two markets with sufficient history")
    pairs: list[tuple[np.ndarray, np.ndarray, float]] = []
    attempts = 0
    while len(pairs) < DCC_PAIRS and attempts < 20 * DCC_PAIRS:
        attempts += 1
        i, j = rng.choice(len(columns), size=2, replace=False)
        both = z[[columns[i], columns[j]]].dropna()
        if len(both) < MIN_FIT_OBS:
            continue
        zi, zj = both.iloc[:, 0].to_numpy(), both.iloc[:, 1].to_numpy()
        pairs.append((zi, zj, float(np.corrcoef(zi, zj)[0, 1])))
    if not pairs:
        raise ValueError("No market pair has enough overlapping history to fit DCC")
    result = minimize(
        _dcc_pair_negative_loglik,
        x0=[0.02, 0.95],
        args=(pairs,),
        method="Nelder-Mead",
        options={"xatol": 1e-4, "fatol": 1e-8},
    )
    return float(result.x[0]), float(result.x[1])


def nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    """Clip negative eigenvalues of a pairwise-estimated correlation matrix; unit diagonal."""
    values, vectors = np.linalg.eigh((matrix + matrix.T) / 2)
    fixed = (vectors * np.clip(values, 1e-6, None)) @ vectors.T
    scale = np.sqrt(np.diag(fixed))
    return fixed / np.outer(scale, scale)


@dataclass(frozen=True)
class _YearModel:
    """State fixed for one forecast year: GARCH levels, DCC target and day-level paths."""

    params: dict[str, GarchParams]
    target_variance: pd.Series
    dcc: tuple[float, float]
    target_correlation: np.ndarray
    variance: pd.DataFrame  # next-day variance by date, daily units
    next_q: dict[pd.Timestamp, np.ndarray]


class DccGarchRiskModel:
    """Monthly covariance forecast from DCC-GARCH on daily returns.

    The forecast sums the 21 daily covariance forecasts of the next month, annualized by 12,
    then applies the monthly model's correlation shrinkage and volatility floor. The market
    universe matches DailyCovarianceRiskModel: baseline eligibility and a complete daily window.
    """

    def __init__(
        self,
        daily: pd.DataFrame,
        asset_class: pd.Series,
        window: int,
        lag: int,
        volatility_floor: float,
        correlation_shrinkage: float,
        dynamic_correlation: bool = True,
        seed: int = 0,
        forecast_start: str | None = None,
    ):
        if not 0 < correlation_shrinkage <= 1:
            raise ValueError("Shrinkage must be positive and at most one")
        self.daily = daily
        self.asset_class = asset_class
        self.window = window
        self.lag = check_lag(lag)
        self.volatility_floor = volatility_floor
        self.correlation_shrinkage = correlation_shrinkage
        self.dynamic_correlation = dynamic_correlation
        self.seed = seed
        self.forecast_start = None if forecast_start is None else pd.Period(forecast_start, freq="M")
        self._forecasts: dict[pd.Period, pd.DataFrame] | None = None
        self._years: dict[int, _YearModel] = {}

    def variant(
        self,
        correlation_shrinkage: float | None = None,
        dynamic_correlation: bool | None = None,
        lag: int | None = None,
    ) -> "DccGarchRiskModel":
        """A copy with another shrinkage or correlation setting that reuses the fitted models."""
        other = copy.copy(self)
        other._forecasts = None
        if correlation_shrinkage is not None:
            other.correlation_shrinkage = correlation_shrinkage
        if dynamic_correlation is not None:
            other.dynamic_correlation = dynamic_correlation
        if lag is not None:
            other.lag = check_lag(lag)
        return other

    def fitted_parameters(self) -> pd.DataFrame:
        """DCC (a, b) and pooled GARCH (alpha, beta) by asset class for each fitted year."""
        rows = []
        for year, model in sorted(self._years.items()):
            row = {"year": year, "dcc_a": model.dcc[0], "dcc_b": model.dcc[1]}
            for market, p in model.params.items():
                row[f"{self.asset_class[market]}_alpha"] = p.alpha
                row[f"{self.asset_class[market]}_beta"] = p.beta
            rows.append(row)
        return pd.DataFrame(rows).set_index("year")

    def _year_model(self, year: int) -> _YearModel:
        if year not in self._years:
            self._years[year] = self._fit_year(year)
        return self._years[year]

    def _fit_year(self, year: int) -> _YearModel:
        fit = self.daily.loc[: f"{year - 1}-12-31"]
        counts = fit.notna().sum()
        modelled = list(counts.index[counts >= MIN_FIT_OBS])
        if len(modelled) < 2:
            raise ValueError(
                f"DCC refit for {year} requires two markets with at least {MIN_FIT_OBS} "
                f"daily observations through {year - 1}-12-31"
            )
        target = (fit[modelled] ** 2).mean()
        params = {}
        for group in sorted(set(self.asset_class.reindex(modelled).dropna())):
            members = [m for m in modelled if self.asset_class[m] == group]
            series = [fit[m].dropna().to_numpy() for m in members]
            fitted = fit_pooled_garch(series)
            params.update({m: fitted for m in members})
        through = self.daily.loc[: f"{year}-12-31", modelled]
        variance, standardized = {}, {}
        for market in modelled:
            returns = through[market].dropna()
            p = params[market]
            h = garch_variance(
                returns.to_numpy(),
                target[market] * (1 - p.alpha - p.beta),
                p.alpha,
                p.beta,
                target[market],
            )
            index = list(returns.index)
            variance[market] = pd.Series(h[1:], index=index)  # variance for the day after each date
            standardized[market] = returns / np.sqrt(pd.Series(h[:-1], index=index))
        z = pd.DataFrame(standardized).reindex(through.index)
        rng = np.random.default_rng(self.seed + year)
        dcc = fit_dcc(z.loc[: f"{year - 1}-12-31"], rng)
        raw = (
            z.loc[: f"{year - 1}-12-31"].corr(min_periods=MIN_FIT_OBS).fillna(0.0).to_numpy().copy()
        )
        np.fill_diagonal(raw, 1.0)
        target_corr = nearest_correlation(raw)
        a, b = dcc
        q = target_corr.copy()
        month_ends = through.groupby(through.index.to_period("M")).tail(1).index
        wanted = set(month_ends)
        start = max(0, len(z) - DCC_WARMUP_DAYS - int((z.index > f"{year - 1}-12-31").sum()))
        next_q = {}
        values = np.nan_to_num(z.to_numpy())
        for t in range(start, len(z)):
            q = (1 - a - b) * target_corr + a * np.outer(values[t], values[t]) + b * q
            if z.index[t] in wanted:
                next_q[z.index[t]] = q.copy()
        return _YearModel(
            params, target, dcc, target_corr, pd.DataFrame(variance).reindex(through.index), next_q
        )

    def _month_forecast(self, model: _YearModel, date: pd.Timestamp) -> pd.DataFrame:
        columns = list(model.target_variance.index)
        persistence = pd.Series({m: p.alpha + p.beta for m, p in model.params.items()})
        h_next = model.variance.loc[date, columns]
        a, b = model.dcc
        q_next = model.next_q[date] if self.dynamic_correlation else model.target_correlation
        total = np.zeros((len(columns), len(columns)))
        for k in range(HORIZON_DAYS):
            h = model.target_variance + persistence**k * (h_next - model.target_variance)
            q = model.target_correlation + (a + b) ** k * (q_next - model.target_correlation)
            scale = np.sqrt(np.diag(q))
            sd = np.sqrt(h.to_numpy())
            total += (q / np.outer(scale, scale)) * np.outer(sd, sd)
        return pd.DataFrame(total * MONTHS_PER_YEAR, index=columns, columns=columns)

    def _forecast_all(self, months: pd.PeriodIndex, wanted: pd.DataFrame) -> dict:
        forecasts: dict[pd.Period, pd.DataFrame] = {}
        active = months[wanted.any(axis=1).to_numpy()]
        # The refit using December may first be used when December is in the
        # information set: February for lag=2, January for the usual lag=1.
        fit_years = {month: (month - self.lag + 1).year for month in active}
        for year in sorted(set(fit_years.values())):
            model = self._year_model(year)
            ends = {d.to_period("M"): d for d in model.next_q}
            for month in active:
                if fit_years[month] != year:
                    continue
                date = ends[month - self.lag]
                forecasts[month] = self._month_forecast(model, date)
        return forecasts

    def _universe(self, data: MarketData) -> pd.DataFrame:
        check_monthly_calendar(data.returns)
        eligible = complete_monthly_window(data.returns, self.window)
        eligible = eligible.shift(self.lag, fill_value=False)
        if self.forecast_start is not None:
            eligible.loc[eligible.index < self.forecast_start] = False
        return eligible

    def _ensure(self, data: MarketData) -> dict[pd.Period, pd.DataFrame]:
        if self._forecasts is None:
            self._forecasts = self._forecast_all(data.returns.index, self._universe(data))
        return self._forecasts

    def volatility(self, data: MarketData) -> pd.DataFrame:
        universe = self._universe(data)
        vol = pd.DataFrame(np.nan, index=data.returns.index, columns=data.returns.columns)
        for month, matrix in self._ensure(data).items():
            markets = [m for m in matrix.index if universe.loc[month, m]]
            start, end = window_dates(month, self.lag, self.window)
            window = self.daily.loc[start:end, markets]
            usable = window.columns[window.notna().all()]
            vol.loc[month, usable] = np.sqrt(np.diag(matrix.loc[usable, usable]))
        return vol

    def covariances(self, data, eligible):
        forecasts = self._ensure(data)
        covariance, details = {}, {}
        size = data.returns.shape[1]
        for month in eligible.index:
            ids = np.flatnonzero(eligible.loc[month].to_numpy())
            matrix = np.zeros((size, size))
            eigenvalue = np.nan
            if len(ids):
                markets = list(data.returns.columns[ids])
                raw = forecasts[month].loc[markets, markets].to_numpy()
                vol = np.sqrt(np.diag(raw))
                correlation = raw / np.outer(vol, vol)
                matrix[np.ix_(ids, ids)] = shrunk_covariance(
                    vol, correlation, self.volatility_floor, self.correlation_shrinkage
                )
                eigenvalue = float(np.linalg.eigvalsh(matrix[np.ix_(ids, ids)]).min())
            covariance[month] = matrix
            details[month] = {
                "information_through": month - self.lag,
                "estimation_start": pd.NaT,
                "min_eigenvalue": eigenvalue,
            }
        return covariance, details
