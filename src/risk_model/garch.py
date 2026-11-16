"""DCC-GARCH covariance forecasts from daily returns (Engle 2002), refit each January.

Each market has a GARCH(1,1) variance with variance targeting. The (alpha, beta) pair is
pooled by asset class so markets with short histories get stable estimates. Correlations
follow DCC on the standardized residuals, with the two DCC parameters fitted by composite
likelihood on random pairs (Engle, Shephard and Sheppard 2008). Gaussian quasi-likelihood.
Forecasts for month t use daily returns through the end of month t - lag only. January
parameter refits use the prior December and become available after the configured lag.

Missing daily observations remain on the calendar. Variance uses its conditional expected
shock; DCC uses Gaussian conditional second moments given the observed residuals. This is a
missing-observation QML approximation, not an assertion that an unavailable return was zero.
"""

import copy
from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter

from src.models import MarketData
from src.risk_model.base import check_lag, check_monthly_calendar
from src.risk_model.daily import complete_monthly_window, shrunk_covariance

HORIZON_DAYS = 21
MIN_FIT_OBS = 250
DCC_PAIRS = 100
DCC_WARMUP_DAYS = 1500
MONTHS_PER_YEAR = 12
RECURRENCE_BLOCK = 128  # bounded products avoid underflow in the affine variance recursion


@dataclass(frozen=True)
class GarchParams:
    alpha: float
    beta: float


def garch_variance(
    returns: np.ndarray, omega: float, alpha: float, beta: float, start: float
) -> np.ndarray:
    """Conditional variances h[0..T]; h[t] uses returns before t, h[T] is the next-day forecast."""
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 1 or np.isinf(returns).any():
        raise ValueError("GARCH returns must be a one-dimensional finite-or-missing history")
    if not (np.isfinite([omega, alpha, beta, start]).all()
            and omega > 0 and start > 0 and alpha >= 0 and beta >= 0 and alpha + beta < 1):
        raise ValueError("GARCH needs positive variance levels and stationary nonnegative parameters")
    if np.isfinite(returns).all():
        shocks = np.concatenate(([start], returns**2))
        h, _ = lfilter([1.0], [1.0, -beta], omega + alpha * shocks, zi=[beta * start])
        return h
    h = np.empty(len(returns) + 1)
    h[0] = omega + (alpha + beta) * start
    # h[t+1] = intercept[t] + coefficient[t]*h[t]. Vectorize short affine blocks;
    # fitting long, partially observed histories otherwise repeats Python day loops.
    if beta >= 0.01:
        observed = np.isfinite(returns)
        coefficient = np.where(observed, beta, alpha + beta)
        intercept = omega + alpha * np.where(observed, returns, 0.0)**2
        for begin in range(0, len(returns), RECURRENCE_BLOCK):
            end = min(begin + RECURRENCE_BLOCK, len(returns))
            products = np.cumprod(coefficient[begin:end])
            h[begin+1:end+1] = products * (h[begin] + np.cumsum(intercept[begin:end]/products))
        return h
    for i, value in enumerate(returns):
        shock = value**2 if np.isfinite(value) else h[i]
        h[i + 1] = omega + alpha * shock + beta * h[i]
    return h


def _pooled_negative_loglik(theta, series: list[np.ndarray]) -> float:
    persistence, share = theta
    alpha, beta = persistence * share, persistence * (1 - share)
    total, count = 0.0, 0
    for returns in series:
        observed = np.isfinite(returns)
        target = float(np.mean(returns[observed]**2))
        h = garch_variance(returns, target * (1 - persistence), alpha, beta, target)[:-1]
        total += float(np.sum(np.log(h[observed]) + returns[observed]**2 / h[observed]))
        count += int(observed.sum())
    return total / count


def _checked_fit(result, name, admissible, diagnostics=None):
    theta = np.asarray(result.x, dtype=float)
    if (not result.success or theta.shape != (2,) or not np.isfinite(theta).all()
            or not np.isfinite(result.fun) or not admissible(theta)):
        raise ValueError(f"{name} estimation failed: {result.message}; parameters={theta}, "
                         f"objective={result.fun}")
    if diagnostics is not None:
        diagnostics.update(success=True, objective=float(result.fun),
                           iterations=int(getattr(result, "nit", 0)))
    return theta


def fit_pooled_garch(series: list[np.ndarray], diagnostics=None) -> GarchParams:
    """Common (alpha, beta) for several markets, each with its own long-run variance."""
    series = [np.asarray(returns, dtype=float) for returns in series]
    if not series:
        raise ValueError("GARCH estimation needs at least one market history")
    for returns in series:
        observed = returns[np.isfinite(returns)]
        if (returns.ndim != 1 or np.isinf(returns).any() or len(observed) < MIN_FIT_OBS
                or not 0 < np.mean(observed**2) < np.inf):
            raise ValueError("GARCH estimation requires positive variance and at least "
                             f"{MIN_FIT_OBS} finite daily observations per market")
    result = minimize(
        _pooled_negative_loglik,
        x0=[0.97, 0.06],
        args=(series,),
        bounds=[(0.5, 0.9995), (0.005, 0.5)],
        method="L-BFGS-B",
    )
    persistence, share = _checked_fit(
        result, "GARCH", lambda x: 0.5 <= x[0] <= 0.9995 and 0.005 <= x[1] <= 0.5,
        diagnostics,
    )
    return GarchParams(persistence * share, persistence * (1 - share))


def _dcc_pair_negative_loglik(theta, pairs: list[tuple[np.ndarray, np.ndarray, float]]) -> float:
    a, b = theta
    if a < 0 or b < 0 or a + b >= 0.9999:
        return 1e10
    if any(not (np.isfinite(zi).all() and np.isfinite(zj).all()) for zi, zj, _ in pairs):
        return _missing_pair_loglik(a, b, pairs)
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


def _missing_pair_loglik(a, b, pairs):
    """Calendar-preserving pair filters, batched across pairs; observe density only jointly.

    A single observed residual updates the missing residual's Gaussian conditional second
    moments. Neither-observed days advance the state using its expected shock correlation.
    """
    left = np.column_stack([zi for zi, _, _ in pairs])
    right = np.column_stack([zj for _, zj, _ in pairs])
    targets = np.array([target for _, _, target in pairs])
    q_left, q_right, q_cross = np.ones(len(pairs)), np.ones(len(pairs)), targets.copy()
    total, count = 0.0, 0
    for zi, zj in zip(left, right, strict=True):
        rho = np.clip(q_cross / np.sqrt(q_left * q_right), -0.999, 0.999)
        observed_i, observed_j = np.isfinite(zi), np.isfinite(zj)
        both = observed_i & observed_j
        if both.any():
            r, x, y = rho[both], zi[both], zj[both]
            total += float(np.sum(np.log1p(-r**2) + (x*x + y*y - 2*r*x*y) / (1-r*r)))
            count += int(both.sum())
        x = np.where(observed_i, zi, 0.0)
        y = np.where(observed_j, zj, 0.0)
        shock_i = np.where(observed_i, x*x, np.where(observed_j, 1-rho*rho+rho*rho*y*y, 1))
        shock_j = np.where(observed_j, y*y, np.where(observed_i, 1-rho*rho+rho*rho*x*x, 1))
        cross = np.where(both, x*y, rho*np.where(observed_i, x*x, np.where(observed_j, y*y, 1)))
        q_left = 1-a-b + a*shock_i + b*q_left
        q_right = 1-a-b + a*shock_j + b*q_right
        q_cross = (1-a-b)*targets + a*cross + b*q_cross
    return total / count


def conditional_residual_moment(residual, q):
    """E[z z' | observed z] under the current Gaussian correlation; no zero imputation."""
    residual = np.asarray(residual, dtype=float)
    scale = np.sqrt(np.diag(q))
    correlation = q / np.outer(scale, scale)
    observed = np.isfinite(residual)
    if observed.all():
        return np.outer(residual, residual)
    if not observed.any():
        return correlation
    missing = ~observed
    block = correlation[np.ix_(missing, observed)]
    observed_block = correlation[np.ix_(observed, observed)]
    mean = np.zeros(len(residual))
    mean[observed] = residual[observed]
    mean[missing] = block @ np.linalg.solve(observed_block, residual[observed])
    covariance = np.zeros_like(q)
    covariance[np.ix_(missing, missing)] = (
        correlation[np.ix_(missing, missing)]
        - block @ np.linalg.solve(observed_block, block.T)
    )
    return np.outer(mean, mean) + covariance


def fit_dcc(z: pd.DataFrame, rng: np.random.Generator, diagnostics=None) -> tuple[float, float]:
    """DCC (a, b) from composite likelihood over random market pairs with enough overlap."""
    if np.isinf(z.to_numpy()).any():
        raise ValueError("DCC residuals must be finite or explicitly missing")
    columns = list(z.columns)
    if len(columns) < 2:
        raise ValueError("DCC estimation requires at least two markets with sufficient history")
    pairs: list[tuple[np.ndarray, np.ndarray, float]] = []
    attempts = 0
    while len(pairs) < DCC_PAIRS and attempts < 20 * DCC_PAIRS:
        attempts += 1
        i, j = rng.choice(len(columns), size=2, replace=False)
        pair = z[[columns[i], columns[j]]]
        observed = pair.notna().all(axis=1)
        if int(observed.sum()) < MIN_FIT_OBS:
            continue
        zi, zj = pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()
        target = float(np.corrcoef(zi[observed], zj[observed])[0, 1])
        if not np.isfinite(target) or abs(target) >= 1:
            continue
        pairs.append((zi, zj, target))
    if not pairs:
        raise ValueError("No market pair has enough overlapping history to fit DCC")
    result = minimize(
        _dcc_pair_negative_loglik,
        x0=[0.02, 0.95],
        args=(pairs,),
        method="Nelder-Mead",
        options={"xatol": 1e-4, "fatol": 1e-8},
    )
    a, b = _checked_fit(result, "DCC", lambda x: x[0] >= 0 and x[1] >= 0
                        and x.sum() < 0.9999, diagnostics)
    if diagnostics is not None:
        diagnostics["pairs"] = len(pairs)
    return float(a), float(b)


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
    universe requires the complete prior monthly history, at least 250 observations at the
    annual fit, and an observed daily return in the information-cutoff month. Missing daily
    observations advance conditional moments rather than fabricating zero returns.
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
        if (not isinstance(daily.index, pd.DatetimeIndex) or daily.empty
                or not daily.index.is_unique or not daily.index.is_monotonic_increasing
                or not daily.columns.is_unique or np.isinf(daily.to_numpy()).any()):
            raise ValueError("DCC daily history needs unique ordered dates/markets and "
                             "finite-or-missing returns")
        if asset_class.reindex(daily.columns).isna().any():
            raise ValueError("Every DCC market needs a declared asset class")
        if not isinstance(window, int) or window < 1:
            raise ValueError("DCC eligibility window must be a positive integer")
        if not np.isfinite(volatility_floor) or volatility_floor < 0:
            raise ValueError("DCC volatility floor must be finite and nonnegative")
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
        self._fit_diagnostics: dict[int, dict] = {}
        self._coverage: dict[tuple[pd.Period, str], dict] = {}

    def variant(
        self,
        correlation_shrinkage: float | None = None,
        dynamic_correlation: bool | None = None,
        lag: int | None = None,
    ) -> "DccGarchRiskModel":
        """A copy with another shrinkage or correlation setting that reuses the fitted models."""
        other = copy.copy(self)
        other._forecasts = None
        other._coverage = {}
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
            row.update(self._fit_diagnostics.get(year, {}))
            for market, p in model.params.items():
                row[f"{self.asset_class[market]}_alpha"] = p.alpha
                row[f"{self.asset_class[market]}_beta"] = p.beta
            rows.append(row)
        return pd.DataFrame(rows).set_index("year")

    def coverage_diagnostics(self) -> pd.DataFrame:
        """Observed/missing counts and latest actual daily return for each forecast market."""
        return pd.DataFrame(self._coverage.values())

    def _year_model(self, year: int) -> _YearModel:
        if year not in self._years:
            self._years[year] = self._fit_year(year)
        return self._years[year]

    def _fit_year(self, year: int) -> _YearModel:
        started = perf_counter()
        fit = self.daily.loc[: f"{year - 1}-12-31"]
        counts = fit.notna().sum()
        target = (fit ** 2).mean()
        positive_target = np.isfinite(target) & target.gt(0)
        modelled = list(counts.index[(counts >= MIN_FIT_OBS) & positive_target])
        if len(modelled) < 2:
            raise ValueError(
                f"DCC refit for {year} requires two markets with at least {MIN_FIT_OBS} "
                f"daily observations and positive variance through {year - 1}-12-31"
            )
        diagnostics: dict[str, object] = {
            "fit_information_through": f"{year - 1}-12-31",
            "excluded_nonpositive_targets": ",".join(target.index[~positive_target]),
        }
        target = target[modelled]
        params = {}
        for group in sorted(set(self.asset_class.reindex(modelled).dropna())):
            members = [m for m in modelled if self.asset_class[m] == group]
            series = [fit[m].to_numpy() for m in members]
            record: dict[str, object] = {}
            try:
                fitted = fit_pooled_garch(series, diagnostics=record)
            except ValueError as error:
                raise ValueError(f"GARCH refit {year}, asset class {group}: {error}") from error
            diagnostics.update({f"{group}_{key}": value for key, value in record.items()})
            params.update({m: fitted for m in members})
        through = self.daily.loc[: f"{year}-12-31", modelled]
        variance, standardized = {}, {}
        for market in modelled:
            returns = through[market]
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
        record = {}
        try:
            dcc = fit_dcc(z.loc[: f"{year - 1}-12-31"], rng, diagnostics=record)
        except ValueError as error:
            raise ValueError(f"DCC refit {year}: {error}") from error
        diagnostics.update({f"dcc_{key}": value for key, value in record.items()})
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
        values = z.to_numpy()
        for t in range(start, len(z)):
            moment = conditional_residual_moment(values[t], q)
            q = (1 - a - b) * target_corr + a * moment + b * q
            if z.index[t] in wanted:
                next_q[z.index[t]] = q.copy()
        diagnostics["fit_seconds"] = perf_counter() - started
        self._fit_diagnostics[year] = diagnostics
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
        eligible.loc[:, ~eligible.columns.isin(self.daily.columns)] = False
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
            cutoff = month - self.lag
            window = self.daily.loc[(cutoff-self.window+1).start_time:cutoff.end_time, markets]
            recent = self.daily.loc[cutoff.start_time:cutoff.end_time, markets].notna().any()
            usable = recent.index[recent]
            for market in markets:
                self._coverage[month, market] = {
                    "month": month, "market": market, "observed_daily": int(window[market].notna().sum()),
                    "missing_daily": int(window[market].isna().sum()),
                    "last_observed": window[market].last_valid_index(),
                    "observed_in_cutoff_month": bool(recent[market]),
                }
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
