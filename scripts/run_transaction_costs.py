"""Transaction cost tests C0, C3, C4 and C5 on the configured DCC-GARCH TREND strategy.

C0 re-runs the engine at each cost. C3, C4 and C5 price the trades of the 2 bps path with a
richer cost (first order: positions are not re-optimised), and C0 measures how large that
approximation is.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import run_band_experiment as band_experiment

from src.backtest.engine import simulate
from src.backtest.performance import sharpe_ratio
from src.backtest.qps_baseline import portfolio_limits
from src.config import ASSET_MAP_PATH, CONFIG_DIR, PROJECT_ROOT
from src.data_loader import load_daily_bars
from src.data_processing.endpoints import endpoints
from src.portfolio_construction import BandPolicy
from src.transaction_cost_model import LinearBpsCost

BPS = 1e4
MONTHS_PER_YEAR = 12


def load_strategy(reference):
    """Targets, covariance forecasts and inputs of the band experiment (about a minute)."""
    spec = json.loads((CONFIG_DIR / "band_experiment.json").read_text())
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    settings.update(bands=spec["bands"], cost_scenarios_bps=spec["cost_scenarios_bps"])
    base = json.loads((PROJECT_ROOT / settings["base_config"]).read_text())
    returns, source, known, meta, _ = band_experiment.load_inputs(reference)
    targets, covariance, _, _ = band_experiment.forecasts(
        returns, source, known, meta, base, settings
    )
    sample = returns.loc[base["start"] : base["end"]]
    return dict(
        sample=sample,
        source=source.loc[sample.index],
        known=known.loc[sample.index],
        targets=targets["trend"],
        covariance=covariance,
        limits=portfolio_limits(settings),
        asset_class=pd.read_csv(ASSET_MAP_PATH, index_col=0).AssetClass.reindex(sample.columns),
    )


def run_trend(strategy, bps, band):
    detail = {}
    policy = BandPolicy(strategy["covariance"], strategy["limits"], band)
    ledger, _ = simulate(
        strategy["sample"],
        strategy["targets"],
        LinearBpsCost(bps),
        strategy["source"],
        position_policy=policy,
        source_known_at=strategy["known"],
        instrument_details=detail,
    )
    return ledger, detail


def net_stats(net):
    """Annualised mean, Sharpe and CAGR of a monthly net return series."""
    wealth = (1 + net).prod()
    return dict(
        mean_ann=net.mean() * MONTHS_PER_YEAR,
        sharpe=sharpe_ratio(net),
        cagr=wealth ** (MONTHS_PER_YEAR / len(net)) - 1 if wealth > 0 else np.nan,
    )


def crossing(fn, low, high, iterations=40):
    """Where a decreasing fn crosses zero; an engine failure counts as non-positive."""

    def positive(x):
        try:
            return fn(x) > 0
        except ValueError:
            return False

    if not positive(low):
        return np.nan
    if positive(high):
        return np.inf
    for _ in range(iterations):
        middle = (low + high) / 2
        low, high = (middle, high) if positive(middle) else (low, middle)
    return (low + high) / 2


# ---------------------------------------------------------------- C0: engine stress grid


def stress_grid(strategy, spec):
    band, reference = spec["band"], spec["reference_bps"]
    base, _ = run_trend(strategy, reference, band)
    rows = []
    for bps in spec["stress_grid_bps"]:
        ledger, _ = run_trend(strategy, bps, band)
        first_order = net_stats(base.gross_return - base.turnover * bps / BPS)
        rows.append(
            dict(
                bps=bps,
                **net_stats(ledger.net_return),
                turnover_ann=ledger.turnover.mean() * MONTHS_PER_YEAR,
                cost_ann=ledger.cost.mean() * MONTHS_PER_YEAR,
                limit_override_months=int(ledger.limit_override.sum()),
                skipped_resizes=int(ledger.band_skipped_resizes.sum()),
                first_order_sharpe=first_order["sharpe"],
                first_order_cagr=first_order["cagr"],
            )
        )
    return pd.DataFrame(rows)


def breakevens(strategy, spec, grid):
    band, reference = spec["band"], spec["reference_bps"]
    sharpe_floor = grid.set_index("bps").sharpe[reference] - spec["sharpe_tolerance"]
    low, high = spec["breakeven_search_bps"]

    def stats(bps):
        return net_stats(run_trend(strategy, bps, band)[0].net_return)

    base, _ = run_trend(strategy, reference, band)
    first_order = base.gross_return.mean() / base.turnover.mean() * BPS
    return pd.Series(
        {
            "net mean return reaches zero (engine)": crossing(
                lambda x: stats(x)["mean_ann"], low, high
            ),
            f"net Sharpe falls {spec['sharpe_tolerance']} (engine)": crossing(
                lambda x: stats(x)["sharpe"] - sharpe_floor, low, high
            ),
            "net mean return reaches zero (first order)": first_order,
        },
        name="bps per unit traded",
    )


# ---------------------------------------------------------------- shared trade panel


def executed_trades(strategy, spec):
    """Traded notional (engine basis) and signed net trade per market-month at the base cost."""
    bps = spec["reference_bps"]
    ledger, detail = run_trend(strategy, bps, spec["band"])
    traded = detail["cost"] / (bps / BPS)
    returns = strategy["sample"].fillna(0.0)
    drifted = (detail["exposure"] * (1 + returns)).div(1 + ledger.net_return, axis=0)
    signed = detail["exposure"] - drifted.shift(1).fillna(0.0)
    mismatch = (signed.abs().sum(axis=1) - traded.sum(axis=1)).abs() > 1e-9
    assert mismatch.sum() <= 2, "only the source switch and terminal liquidation may differ"
    np.testing.assert_allclose(traded.sum(axis=1) * bps / BPS, ledger.cost, atol=1e-12)
    return ledger, traded, signed


def monthly_volatility(strategy):
    """Annualised volatility forecast per market, as known when each month's trade is made.

    A zero forecast after a market's first one (RL in 2009-01, at the source switch) is a gap
    in the forecast, not zero risk, so the previous forecast is carried forward.
    """
    columns = strategy["sample"].columns
    rows = {m: np.sqrt(np.diag(strategy["covariance"][m])) for m in strategy["sample"].index}
    forecast = pd.DataFrame(rows, index=columns).T
    return forecast.where(forecast > 0).ffill().fillna(0.0)


# ---------------------------------------------------------------- C3: spread tied to volatility


def volatility_multiplier(volatility, traded):
    """sigma / own median sigma, over months where the market has a risk forecast."""
    listed = volatility.where(volatility > 0)
    multiplier = listed / listed.median()
    assert not (traded.gt(0) & multiplier.isna()).any().any(), "trade without a risk forecast"
    return multiplier.fillna(1.0)


def spread_tests(ledger, traded, multiplier, spec):
    """Flat and volatility-scaled half-spread; the last case holds total cost at the flat rate."""
    reference = spec["reference_bps"]
    scaled_units = (traded * multiplier).sum(axis=1)
    matched = reference * traded.sum().sum() / scaled_units.sum()
    cases = [(f"{h} bps", h, h) for h in spec["spread_half_bps"]]
    cases.append((f"{matched:.2f} bps scaled vs {reference} bps flat", reference, matched))
    rows = []
    for label, flat_bps, scaled_bps in cases:
        for name, units, bps in [
            ("flat", traded.sum(axis=1), flat_bps),
            ("volatility-scaled", scaled_units, scaled_bps),
        ]:
            cost = units * bps / BPS
            rows.append(
                dict(
                    case=label,
                    spread=name,
                    cost_ann_bps=cost.mean() * MONTHS_PER_YEAR * BPS,
                    effective_bps=cost.sum() / traded.sum().sum() * BPS,
                    **net_stats(ledger.gross_return - cost),
                )
            )
    return pd.DataFrame(rows)


def spread_regimes(traded, multiplier, asset_class, spec):
    scaled = traded * multiplier
    monthly = scaled.sum(axis=1) / traded.sum(axis=1).replace(0, np.nan)
    high = monthly.ge(monthly.quantile(1 - spec["high_volatility_month_share"]))
    by_class = scaled.T.groupby(asset_class).sum().sum(axis=1) / traded.T.groupby(
        asset_class
    ).sum().sum(axis=1)
    summary = pd.Series(
        {
            "multiplier, all months": scaled.sum().sum() / traded.sum().sum(),
            "multiplier, highest-volatility months": scaled[high].sum().sum()
            / traded[high].sum().sum(),
            "share of turnover in highest-volatility months": traded[high].sum().sum()
            / traded.sum().sum(),
        }
    )
    return pd.concat([summary, by_class.rename(lambda c: f"multiplier, {c}")]).rename("value")


# ---------------------------------------------------------------- C4: convex impact


def notional_per_contract(close, spec):
    multiplier = pd.Series(spec["contract_multiplier"]).reindex(close.columns)
    value = close * multiplier
    for market, size in spec["inverse_quoted_contract_size"].items():
        value[market] = size / close[market]
    return value


def price_history(strategy, bars, spec):
    """Close and average daily volume (contracts) at each month's trade date (prior endpoint)."""
    sample, source = strategy["sample"], strategy["source"]
    months = pd.period_range(sample.index[0] - 1, sample.index[-1], freq="M")
    close = pd.DataFrame(np.nan, index=sample.index, columns=sample.columns)
    volume = close.copy()
    for market in sample.columns:
        for held in source[market].unique():
            data = bars[held]
            average = data.Volume.rolling(
                spec["adv_window_days"], min_periods=spec["adv_min_days"]
            ).mean()
            dates = endpoints(data, months).price_date.iloc[:-1]
            rows = source[market].eq(held).to_numpy() & dates.notna().to_numpy()
            when = pd.DatetimeIndex(dates[rows])
            close.loc[rows, market] = data.Close.loc[when].to_numpy()
            volume.loc[rows, market] = average.loc[when].to_numpy()
    return close, volume


def impact_cost(traded, volatility, dollar_adv, aum, coefficient, spec):
    """Y * sigma_daily * sqrt(Q / ADV) per unit traded, as a fraction of NAV; Q = AUM * traded."""
    daily = volatility / np.sqrt(spec["trading_days_per_year"])
    participation = (aum * traded) / dollar_adv
    return coefficient * daily * np.sqrt(participation.fillna(0.0)) * traded, participation


def impact_tests(ledger, traded, volatility, dollar_adv, spec):
    rows = []
    flat = ledger.gross_return - ledger.cost
    for scale in spec["adv_scale"]:
        for coefficient in spec["impact_coefficient"]:
            for aum in spec["aum_grid"]:
                cost, participation = impact_cost(
                    traded, volatility, dollar_adv * scale, aum, coefficient, spec
                )
                total = cost.sum(axis=1)
                rows.append(
                    dict(
                        adv_scale=scale,
                        coefficient=coefficient,
                        aum=aum,
                        impact_ann_bps=total.mean() * MONTHS_PER_YEAR * BPS,
                        impact_bps_per_unit=total.sum() / traded.sum().sum() * BPS,
                        max_participation=participation.where(traded > 0).max().max(),
                        trades_above_10pct_adv=(participation.where(traded > 0) > 0.1).sum().sum()
                        / (traded > 0).sum().sum(),
                        **net_stats(flat - total),
                    )
                )
    return pd.DataFrame(rows)


def capacity(ledger, traded, volatility, dollar_adv, spec):
    flat = ledger.gross_return - ledger.cost
    rows = []
    for scale in spec["adv_scale"]:
        for coefficient in spec["impact_coefficient"]:
            rows.append(
                capacity_row(flat, traded, volatility, dollar_adv * scale, coefficient, spec)
                | {"adv_scale": scale, "coefficient": coefficient}
            )
    return pd.DataFrame(rows)


def capacity_row(flat, traded, volatility, dollar_adv, coefficient, spec):
    """AUM at which Sharpe falls by the tolerance, and at which net mean return is zero."""

    def stats(log_aum):
        cost, _ = impact_cost(traded, volatility, dollar_adv, 10**log_aum, coefficient, spec)
        return net_stats(flat - cost.sum(axis=1))

    target = net_stats(flat)["sharpe"] - spec["sharpe_tolerance"]
    bounds = tuple(np.log10(spec["capacity_search_aum"]))
    return {
        "aum_sharpe_falls_by_tolerance": 10
        ** crossing(lambda x: stats(x)["sharpe"] - target, *bounds),
        "aum_net_return_zero": 10 ** crossing(lambda x: stats(x)["mean_ann"], *bounds),
    }


def impact_by_period(traded, volatility, dollar_adv, spec):
    """Impact at the reference AUM and first coefficient, by subperiod."""
    cost, _ = impact_cost(
        traded, volatility, dollar_adv, spec["reference_aum"], spec["impact_coefficient"][0], spec
    )
    rows = []
    for start, end in spec["subperiods"]:
        window = cost.loc[start:end]
        rows.append(
            {
                "period": f"{start}-{end}",
                "impact_ann_bps": window.sum(axis=1).mean() * MONTHS_PER_YEAR * BPS,
                "impact_bps_per_unit": window.sum().sum() / traded.loc[start:end].sum().sum() * BPS,
            }
        )
    return pd.DataFrame(rows)


def impact_by_market(traded, volatility, dollar_adv, asset_class, spec):
    cost, _ = impact_cost(
        traded, volatility, dollar_adv, spec["reference_aum"], spec["impact_coefficient"][0], spec
    )
    annual = cost.sum() * MONTHS_PER_YEAR / len(cost) * BPS
    return pd.DataFrame({"asset_class": asset_class, "impact_bps_ann": annual}).sort_values(
        "impact_bps_ann", ascending=False
    )


# ---------------------------------------------------------------- C5: fill delay


def overnight_gaps(strategy, bars):
    """Close-to-next-open return after each trade date, and the mean gap on the month's other days."""
    sample, source = strategy["sample"], strategy["source"]
    months = pd.period_range(sample.index[0] - 1, sample.index[-1], freq="M")
    trade_gap = pd.DataFrame(np.nan, index=sample.index, columns=sample.columns)
    other_gap = trade_gap.copy()
    for market in sample.columns:
        for held in source[market].unique():
            data = bars[held]
            data = data[data.Open > 0]
            dates = endpoints(data, months).price_date
            overnight = data.Open / data.Close.shift(1) - 1
            for i, month in enumerate(sample.index):
                if source.loc[month, market] != held or pd.isna(dates.iloc[i]):
                    continue
                first = data.index.searchsorted(dates.iloc[i], side="right")
                last = data.index.searchsorted(dates.iloc[i + 1], side="right")
                if first >= len(data) or last - first < 2:
                    continue
                trade_gap.loc[month, market] = overnight.iloc[first]
                other_gap.loc[month, market] = overnight.iloc[first + 1 : last].mean()
    return trade_gap, other_gap


def slippage_tests(signed, trade_gap, other_gap, asset_class, spec):
    """Cost of filling at the next open = signed trade x close-to-open gap (positive = adverse)."""
    covered = (trade_gap.notna() & other_gap.notna()).iloc[
        :-1
    ]  # terminal liquidation has no later open
    trades = signed.iloc[:-1].where(covered, 0.0)
    fill = trades * trade_gap.iloc[:-1].fillna(0.0)
    other = trades * other_gap.iloc[:-1].fillna(0.0)
    attempted = signed.iloc[:-1].abs()

    def summarise(label, window):
        units = trades.loc[window].abs().sum().sum()
        difference = (fill.loc[window] - other.loc[window]).sum(axis=1)
        return dict(
            group=label,
            coverage=units / attempted.loc[window].sum().sum(),
            slippage_bps_per_unit=fill.loc[window].sum().sum() / units * BPS,
            other_days_bps_per_unit=other.loc[window].sum().sum() / units * BPS,
            excess_t=difference.mean() / (difference.std() / np.sqrt(len(difference))),
            slippage_ann_bps=fill.loc[window].sum(axis=1).mean() * MONTHS_PER_YEAR * BPS,
        )

    rows = [summarise("all", slice(None))]
    rows += [summarise(f"{start}-{end}", slice(start, end)) for start, end in spec["subperiods"]]
    classes = pd.DataFrame(
        {
            "slippage_bps_per_unit": fill.T.groupby(asset_class).sum().sum(axis=1)
            / trades.abs().T.groupby(asset_class).sum().sum(axis=1)
            * BPS
        }
    )
    monthly = fill.sum(axis=1).reindex(signed.index, fill_value=0.0)
    return pd.DataFrame(rows), classes, monthly


def combined(ledger, traded, usable, multiplier, volatility, dollar_adv, slippage, spec):
    """Volatility-scaled spread + impact at each AUM + realised fill slippage, all first order."""
    spread = (traded * multiplier).sum(axis=1) * spec["reference_bps"] / BPS
    rows = [dict(case="flat 2 bps", aum=np.nan, **net_stats(ledger.gross_return - ledger.cost))]
    for aum in spec["aum_grid"]:
        impact, _ = impact_cost(
            usable, volatility, dollar_adv, aum, spec["impact_coefficient"][0], spec
        )
        total = spread + impact.sum(axis=1) + slippage
        rows.append(
            dict(
                case="spread + impact + slippage", aum=aum, **net_stats(ledger.gross_return - total)
            )
        )
    return pd.DataFrame(rows)


def main(reference, out):
    if out.exists():
        raise ValueError("Use a new output directory; existing experiments are immutable")
    spec = json.loads((CONFIG_DIR / "transaction_costs.json").read_text())
    analyse(load_strategy(reference), spec, out)


def analyse(strategy, spec, out):
    out.mkdir(parents=True)
    grid = stress_grid(strategy, spec)
    grid.to_csv(out / "c0_stress_grid.csv", index=False)
    breakevens(strategy, spec, grid).to_csv(out / "c0_breakevens.csv")
    ledger, traded, signed = executed_trades(strategy, spec)
    volatility = monthly_volatility(strategy)
    multiplier = volatility_multiplier(volatility, traded)
    spread_tests(ledger, traded, multiplier, spec).to_csv(out / "c3_spread.csv", index=False)
    spread_regimes(traded, multiplier, strategy["asset_class"], spec).to_csv(out / "c3_regimes.csv")
    bars = load_daily_bars()
    close, volume = price_history(strategy, bars, spec)
    contract_value = notional_per_contract(close, spec)
    dollar_adv = volume * contract_value
    dollar_adv = dollar_adv.where(dollar_adv > 0)
    usable = traded.where(dollar_adv.notna(), 0.0)
    pd.Series(
        {"share of traded notional with a usable ADV": usable.sum().sum() / traded.sum().sum()}
    ).to_csv(out / "c4_coverage.csv")
    impact_tests(ledger, usable, volatility, dollar_adv, spec).to_csv(
        out / "c4_impact.csv", index=False
    )
    capacity(ledger, usable, volatility, dollar_adv, spec).to_csv(
        out / "c4_capacity.csv", index=False
    )
    impact_by_period(usable, volatility, dollar_adv, spec).to_csv(
        out / "c4_by_period.csv", index=False
    )
    impact_by_market(usable, volatility, dollar_adv, strategy["asset_class"], spec).to_csv(
        out / "c4_by_market.csv"
    )
    pd.DataFrame(
        {
            "contract_notional_dec2014": contract_value.iloc[-1],
            "asset_class": strategy["asset_class"],
        }
    ).to_csv(out / "c4_contract_values.csv")
    trade_gap, other_gap = overnight_gaps(strategy, bars)
    table, classes, slippage = slippage_tests(
        signed, trade_gap, other_gap, strategy["asset_class"], spec
    )
    table.to_csv(out / "c5_slippage.csv", index=False)
    classes.to_csv(out / "c5_by_class.csv")
    combined(ledger, traded, usable, multiplier, volatility, dollar_adv, slippage, spec).to_csv(
        out / "combined.csv", index=False
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.reference.resolve(), args.output.resolve())
