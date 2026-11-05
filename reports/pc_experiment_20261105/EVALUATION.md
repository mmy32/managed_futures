# Lecture 9 enhancement: implementation and evidence

**Decision: retain the existing 10% bands.** The cost-aware optimizer is implemented and validated as an opt-in research policy. It reduces turnover, but this development experiment does not establish a net-return edge.

The strategy still follows the existing futures trend signals. The enhancement chooses trades for the portfolio as a whole: pay to follow the desired exposures more closely, or save fees by tolerating a small difference in forecast risk. Correlation lets the optimizer recognize when another position already supplies similar exposure. Its possible edge is retaining more return after fees; tracking variance is a preference penalty, not an estimated loss of alpha.

## Comparison and measured mechanism

The primary comparison uses the class-specific signals and rescaled DCC-GARCH model from pulled commit `b62d206`. Only the trading policy changes. Every case uses **1.5 bps per unit of absolute one-way turnover**, the same eligible universe, 3x gross cap, 10% annual forecast-risk ceiling, and a two-month information lag. Fees include entry, drift-adjusted resizes, reversals, source close/open trades, forced exits, and terminal liquidation.

The scored calendar is January 1986–December 2014 (348 months), following 120 months of calibration history. All these data were previously inspected; chronological selection does not make them fresh out-of-sample evidence. [Full metrics](configured_lag2/scored_comparison.csv) and the [generated summary](SUMMARY.md) contain returns and risk statistics.

| Policy vs. 10% bands | Turnover reduction | Fee savings, bps/year | Gross return change, bps/year | Net return change, bps/year |
| --- | ---: | ---: | ---: | ---: |
| Fixed gamma 5 | 37.10% | +5.23 | −100.08 | −94.85 |
| Fixed gamma 10 | 21.63% | +3.05 | −47.08 | −44.03 |
| Fixed gamma 20 | 8.70% | +1.23 | −21.73 | −20.51 |
| Chronological walk-forward | 0.64% | +0.09 | −0.33 | −0.24 |

These are annualized means of paired monthly differences, not CAGR differences. At 1.5 bps, the direct savings are too small to offset the gross-return reduction in the fixed policies. More aggressive cost avoidance is not beneficial in this historical comparison. The experiment does not attribute the gross-return differences solely to lower risk: directions, relative exposures, and delayed trades also change.

Walk-forward selection uses only the preceding 60 completed months, updates every 12 months, and retains bands when no fixed-gamma candidate has positive validation uplift. It carries actual drifted holdings and NAV across switches. Of the 348 scored months, it uses bands for 288, gamma 20 for 48, and gamma 10 for 12. This explains why its overall result stays close to the baseline. Artificial final liquidation is excluded from selection scores and included in reported performance.

## Uncertainty and robustness

The walk-forward net difference of **−0.24 bps/year** has these paired block-bootstrap intervals (20,000 draws):

| Block length | Nominal 95% interval, bps/year | Five-comparison adjusted interval, bps/year |
| --- | ---: | ---: |
| 6 months | [−9.84, +9.56] | [−13.02, +13.16] |
| 12 months | [−10.11, +9.11] | [−13.66, +12.23] |

The primary result is inconclusive. Fixed gamma 5 and 10 have negative intervals even after the declared family adjustment; gamma 20's adjusted intervals span zero. These are descriptive intervals on an already inspected dataset, not a correction for all prior research choices. See [all intervals](configured_lag2/paired_intervals.csv).

The common-risk replay brings both original paths' ex ante directions to identical after-entry-fee forecast risk and resimulates trades and NAV. Its walk-forward net change is **−3.97 bps/year**, with a 12-month-block nominal interval of **[−13.42, +4.71]**. It also provides no established edge. This is a direction replay, not a fresh optimization at different risk limits.

Without retuning, the final primary-selected fixed policy (gamma 20) returns **−17.81 bps/year** relative to configured bands at lag one, and **−13.74 bps/year** relative to the original uniform 12-month/rolling-covariance baseline at lag two. Both sensitivities have nominal intervals spanning zero. See [lag-one results](configured_lag1/paired_comparison.csv) and [original-baseline results](rolling_reference_lag2/paired_comparison.csv).

## What improves over the midterm implementation

- Portfolio-wide, correlation-aware trade decisions replace an instrument-by-instrument band in the optional policy. Exact linear fees and forced exits enter the optimization itself.
- Gross exposure and forecast risk are constrained against capital remaining after entry fees, then checked independently using actual trade accounting.
- The evaluation separates fee savings from gross-return changes, preserves state across chronological policy switches, and adds uncertainty and common-risk checks.
- A regression test exposed a DCC January refit using December observations when lag two allowed only data through November. The fix delays that refit until February; the normal lag-one schedule is unchanged.
- Shared forecasts, shared matrix factors, cached parameterized problems, and warm starts make the experiment practical. No custom solver or general optimization framework was added.

These are implemented capability, timing, and evaluation improvements. The measured financial improvement is **lower turnover**, not higher net return. Earlier signal and DCC changes belong to the pulled upstream work and are not claimed as gains from this optimizer.

## Validation, efficiency, and reproducibility

The full suite passes **227 tests**, including analytical optimizer cases, fee/limit checks, future-data mutation, prefix replay, exported-holdings replay, source switches, and DCC timing integration. Changed Python files pass Ruff. Repository-wide checks retain 127 Ruff findings outside those files and five existing Mypy pandas-slicing errors, independently reproduced from a clean archive of `b62d206`.

The full experiment took **79.33 seconds**. Shared primary forecasts used **57.53 seconds**. Each fixed optimizer simulated all 468 historical months in **2.10–2.18 seconds**, against a declared 120-second case budget. Each solved 466 active months and reused 42 problem structures for the changing active dimension. The largest fixed-case 95th-percentile solver time was **5.69 milliseconds**; the largest constraint residual was **1.10e−9**, with maximum guard adjustment **2.06e−9**, both below the independent `1e-7` threshold. The package versions are recorded in [pre_run_record.json](pre_run_record.json).

The original lag-one, 2-bps rolling baseline reproduces to a maximum absolute ledger-field difference of **3.41e−13**. Input hashes, accounting, limits, common-risk equality, and the source/configuration freeze all verify; see [validation.json](validation.json) and [reference reproduction](rolling_reference_lag1/reference_reproduction.json).

The initial strict-precision attempt is retained at [pc_experiment_20261105_failed_precision](../pc_experiment_20261105_failed_precision/failure.json). It stopped on `optimal_inaccurate` at solver tolerance `1e-10`. The successful rerun requests `1e-8`, keeps independent feasibility at `1e-7`, and still rejects inaccurate statuses. The objective, gamma grid, and selection rule were not changed to improve performance.

## Frozen research candidate and limits

The predeclared final trailing-window rule selects **gamma 20** from January 2010–December 2014, with +5.46 bps/year validation uplift after excluding artificial terminal liquidation. This mechanical next-period selection is recorded in [final_selection.json](configured_lag2/final_selection.json); it does **not** override the overall decision to retain production bands. Gamma 20 is frozen for possible independent research evaluation, with 1.5-bps fees and lag two, in [freeze.json](freeze.json) and [source_snapshot.zip](source_snapshot.zip).

No untouched evaluation data were supplied. Evaluation dates, sufficient contiguous warmup, provenance, and execution conventions must be declared before the planned 36-month independent evaluation. The 2014-to-present gap cannot be fabricated. There are zero prospective observations and no promotion or live trading.

Historical results remain conditional on the unverified March 1997 endpoint assumption and unavailable vendor vintages. The model uses zero cash income and ordinary trade costs; regular contract rolls, executable fills, capacity, and market impact remain unestablished. Causal code tests address information timing within the available data, not these unresolved data and execution limitations.
