# Liquidity and funding: implementation feasibility

**Step 5 complete; no production strategy change.** The supplied files support a descriptive activity audit and a conditional collateral-income comparison. They do not yet support an empirical capacity, market-impact, margin or borrowing-cost estimate. Step 6 has not started.

## What the data support

All 62 daily series were audited: 457,155 observations, including 730 zero-volume observations retained in calculations. There are no negative volume/open-interest values or fractional volume observations. Ten rows repeat the preceding full OHLC/volume/OI bar; none belong to a run of five identical bars. Repetition is a review flag, not proof of bad data or a reason to delete observations.

For each holding month in 1976–2014, the diagnostic excludes the latest pre-month bar and uses the preceding 20 recorded observations. It never uses holding-month volume, fills missing history or combines volume across source aliases. Seven calendar days is a descriptive history-age screen, not a trading filter. Source-close trades use the old source; other beginning trades use the current source. Final liquidations are outside this beginning-decision screen.

| Portfolio | Beginning trade-event rows | Positive, complete, recent volume window | Share of summed NAV-normalized trade notional |
|---|---:|---:|---:|
| TREND | 11,788 | 100% | 100% |
| STATIC | 8,661 | 100% | 100% |

Each asset class also has 100% coverage under this screen. Events are execution legs, not independent trade decisions. Notional coverage weights each event by its beginning-month NAV-normalized size; it is not a dollar-volume estimate. **Passing means reported activity data exist; it does not establish that orders are executable at the modeled cost.** Volume units and delivery-contract lineage remain unverified. See [daily audit](output/daily_activity_audit.csv), [class coverage](output/trade_activity_coverage.csv) and the compressed source-specific panels/event joins in `output/`.

## Conditional collateral income

Eight v2 cases compare TREND and STATIC at ordinary costs of 1 and 2 bps, using zero cash income or the workbook's monthly RF as a hypothetical full-capital collateral-income proxy. Both conventions start flat with NAV 1 in January 2000 and liquidate in December 2014. Earlier returns initialize forecasts; the 10% band and existing risk controls remain fixed. No hypothetical roll costs are added.

| Portfolio | Trade bps | Cash convention | CAGR | Zero-rate mean/vol | Excess Sharpe vs RF | Max drawdown |
|---|---:|---|---:|---:|---:|---:|
| TREND | 1 | Zero cash | 9.50% | 0.957 | 0.775 | -14.43% |
| TREND | 1 | RF proxy | 11.49% | 1.138 | 0.959 | -14.39% |
| STATIC | 1 | Zero cash | 7.28% | 0.666 | 0.506 | -37.89% |
| STATIC | 1 | RF proxy | 9.24% | 0.828 | 0.667 | -36.90% |
| TREND | 2 | Zero cash | 9.41% | 0.949 | 0.767 | -14.44% |
| TREND | 2 | RF proxy | 11.40% | 1.130 | 0.950 | -14.40% |
| STATIC | 2 | Zero cash | 7.27% | 0.666 | 0.505 | -37.90% |
| STATIC | 2 | RF proxy | 9.23% | 0.827 | 0.667 | -36.91% |

At 2 bps, TREND CAGR rises from **9.41% to 11.40%**, and STATIC from **7.27% to 9.23%**, with the hypothetical RF income. Average annualized collateral income is about **1.83% of NAV**. This is an arithmetic income average, not the CAGR difference: compounding and subsequent portfolio drift also matter. The matching zero-cash controls use this same 15-year window; they are not the 39-year reference runs.

The workbook RF is used as supplied in decimal monthly units (January 2000: 0.0041 = 0.41%). Income is `RF × (1 − entry fees)`, measured against beginning-period NAV. Terminal fees are paid at the ending endpoint. Holdings and costs are resimulated; current RF affects realized P&L and future drift, never current positions. Cash income stays separate from asset-class trading P&L.

The zero-rate mean/volatility ratio divides annualized mean net return by annualized volatility. The excess Sharpe subtracts the **same monthly workbook RF once from both cash conventions**, then uses excess-return volatility. This distinguishes interest income from trading performance. Actual collateral yield, cash availability and the supplied return series' interest/cost coverage are not verified; the funded cases are sensitivities, not validated total account returns. [All metrics](output/funding_comparison.csv).

## Inputs required before adopting more detailed models

| Proposed model | Missing evidence | Decision |
|---|---|---|
| Participation / capacity | AUM, dated delivery-contract IDs, multipliers, quote units, FX conversion and verified contract-volume units | Do not convert NAV weights into contract orders or participation. |
| Market impact | Spreads, execution horizon, fills/benchmarks and defensible futures-specific calibration | Keep the linear proxy; do not fit unsupported coefficients or add an arbitrary nonlinear solver term. |
| Margin / cash borrowing | Contract margin schedules, balances, buffers, actual collateral yield and financing terms | Do not treat 3× gross exposure as a 2× cash loan. |

The primary reference remains trade-only at 2 bps and the 10% band. The earlier roll sensitivity remains separate. All inputs/history are already inspected; this assessment is not independent validation. The broader research also retains the unverified March 1997 endpoint qualification. A final evaluation needs frozen rules and genuinely untouched history or prospective paper trading.

## Verification and reproduction

All **173 tests pass**, including lagged-volume timing, source mapping, zero retention, missing-RF rejection, current-RF position independence, accounting and risk limits. All eight runs reconcile return components and NAV, with no forecast-risk or gross-limit breaches. All 65 raw input hashes and the Step 2–4 artifact manifests remain unchanged. Primary configuration matches Step 4.

Changed Python files pass Ruff. Repository-wide Ruff reports 110 findings: the existing 12 active-code/notebook findings plus 98 in archived reproduction scripts. Excluding archived reports leaves the same 12 findings. Mypy retains the existing `targets.py:44` slice-index error. Historical artifacts were preserved. The source snapshot, execution logs, manifests and cleanup inventory accompany this report.

[Reproduction instructions](REPRODUCE.md) · [Readiness gates](output/data_gate.json) · [Validation](validation.json)
