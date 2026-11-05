# Fixed strategy and research definitions

The evaluation calendar is January 1976–December 2014. Earlier observations initialize the model; no start date or eligibility threshold is silently changed. January 1976 has seven eligible instruments, below the required ten, so the existing rule leaves both portfolios flat. March 1997 has missing held DT, GS and LX returns, which blocks the full-period comparison under the preserved endpoint policy. See [data status](DATA_STATUS.md), [presentation report](../reports/qps_baseline/REPORT.md) and [endpoint audit](ENDPOINT_REVIEW.md).

## Data, signal and eligibility

Retain the independently audited monthly endpoint construction and its eight documented corrections. Retain ND over EN and SP over ES/SC. Drop duplicate YM and unresolved EC identity. RL/ER form one column; switch permanently from RL to ER only after 36 consecutive ER monthly returns ending no later than t−2. Source dates precede holding months. Neither source choice nor eligibility uses current/future realized availability.

For the original baseline, holding-month t direction is sign(sum of returns t−12 through t−1). The default v2 retains that signal for COMM, EQ and FI; FX averages the signs of the trailing 3- and 12-month return sums. Volatility/correlation estimates use t−36 through t−1. Eligibility requires complete prior signal and risk windows and positive measured volatility; the portfolio is flat below ten eligible instruments. A zero signal is flat. Missing held returns raise an explicit error, including on final liquidation months. They are never filled, dropped or used to change the current portfolio.

The three-calendar-day endpoint freshness rule and bounded raw-date spans are preserved, along with the existing HS and Eurex exceptions. The unresolved March 1997 four-day endpoint gap is not automatically granted another exception. `proposed_endpoint_returns.csv` is review-only and is not consumed by any data loader.

## Risk and position sizing

Let sigma be monthly sample standard deviation × sqrt(12), floored at 2% annually. Let D be its diagonal matrix and R the sample correlation matrix from the common complete prior window. The annual covariance forecast is `Q = D (0.5 R + 0.5 I) D`. Ineligible rows/columns are zero. Positive shrinkage and the volatility floor make the eligible block positive definite.

Initial exposure magnitude is `0.40 / (eligible count × sigma)`. The trend signal supplies direction; STATIC is always long. Proportionally reduce the portfolio to satisfy `sum(abs(w)) ≤ 3` and `sqrt(w'Qw) ≤ 0.10`. Do not scale upward to reach the ceiling. STATIC uses its own all-long covariance forecast, so it need not match trend's absolute holdings. No equal class-risk allocation is imposed.

For actual carried holdings, same-direction positions within `target ± 0.10 abs(target)` are retained; otherwise trade to the nearest band edge. Entries, exits and reversals execute at target immediately. The common limit solver then reduces holdings if needed so `sum(abs(w))/(1−entry_fee) ≤ 3` and `sqrt(w'Qw)/(1−entry_fee) ≤ 0.10`. Risk limits override bands. Configured comparisons use bands 0/10% and costs 0/1/2/5 bps, with 2 bps and a 10% band as the primary case. The completed [cost revision](../reports/cost_revision_20261026/SUMMARY.md) reports all 32 scenarios; earlier 5 bps reports are preserved separately. Earlier diagonal/class-balanced routines remain solely for compatibility and regression tests; the active runner evaluates only the frozen correlated model.

## Accounting and funding

Exposure is measured in units of beginning-month NAV. Same-source traded exposure is `abs(new−carried)`; a source switch charges `abs(new)+abs(carried)` to close/open the actual sources. Initial entry, drift-adjusted rebalancing and final liquidation are charged. Cost rate is bps/10,000, applied to absolute one-way traded notional / beginning-period NAV without halving turnover. The 2 bps primary rate (1 bps sensitivity) is an effective aggregate trading-cost proxy, not an empirically calibrated spread/impact model. The production reference remains trade-only; separately modeled hypothetical rolls are described in the Step 4 section below. Gross return is the exposure/return dot product. Primary net return is gross less entry and liquidation costs, with RF = 0. Holdings carry as `w (1+r)/(1+net_return)`.

Optional collateral funding credits RF on capital after entry fees. Sharpe for that funded net series subtracts the matching monthly RF exactly once, then annualizes the excess mean and sample SD. Missing matching RF fails explicitly. Primary zero-rate Sharpe uses net returns without an additional subtraction. Annual direct cost drag is 12 × mean monthly booked costs; changes in compounded performance also reflect fee-driven changes in NAV and band decisions.

Instrument costs are recorded within the same simulator using actual trades and liquidation. Class net contributions are sums of gross instrument contributions less those instrument costs. With zero interest they reconcile to total monthly net return. Annual mean class contributions add to portfolio annual mean. Wealth-linked cumulative class P&L is `sum_t NAV_start,t × class_net_return,t`; those contributions add to terminal NAV minus initial capital. Class contribution volatilities do not add.

Class forecast volatility contributions are the signed Euler terms `sum_i w_i (Qw)_i / sqrt(w'Qw)` for instruments in each class. They add to total forecast volatility and may be negative for hedges. Average exposure is absolute implemented notional divided by beginning-month NAV; the separate hard-limit diagnostics use after-fee capital.

## Descriptive statistics and autocorrelation

Within the requested 1976–2014 calendar, each class return is the equal-weighted return of its prior-eligible members. The global ten-instrument trading threshold does not suppress descriptive class returns. An empty class is missing. An unknown realized return for any eligible constituent makes the entire class return missing; never omit/reweight that member. Count distinct eligible instruments, observed eligible instrument-months and available class portfolio months separately.

Calculate mean, sample SD and Sharpe from class series, not instrument-level statistics. Annual mean is 12 × monthly mean and annual volatility sqrt(12) × monthly SD. RF is zero. Different class coverage prevents four complete matched 468-month series; report available-history counts prominently. Compounding starts at each class's first eligible observation and stops at an internal unknown return rather than bridging unknown P&L. The lecture's longer descriptive history is not directly comparable.

For each class and monthly lag k = 1,…,12, shift the intact monthly calendar first, then remove missing pairs. Rank the matched variables independently, with average ranks for ties. Standardize both rank variables to sample mean zero and SD one; the OLS slope with an intercept equals Spearman correlation.

Approximate uncertainty uses Bartlett/Newey–West score covariance with bandwidth k, finite-sample multiplier n/(n−2) and t(n−2) intervals. Preserve gaps by inserting zero score rows for unmatched calendar months before lag products; do not compress missing months for HAC. The OLS bread uses the actual n matched observations. Rank-estimation uncertainty is not separately modeled; linear-regression intervals can exceed [−1,1]. All 48 tests are exploratory and unadjusted for multiple comparisons. They do not select the signal horizon.

## Portfolio evaluation and validation

Annual net mean = 12 × monthly mean; net volatility = sqrt(12) × sample monthly SD. CAGR compounds monthly NAV. Drawdown includes initial capital in the running peak. STATIC alpha is the intercept of net trend on net STATIC with an intercept, multiplied by 12; HAC bandwidth 6 is primary, with 3 and 12 also reported and finite-sample/t intervals. No factor or collateral-funded sensitivity is required by the current presentation.

Forecast calibration is `std(gross_return / (forecast_annual / sqrt(12)))`, excluding zero-forecast observations; a value near one indicates better calibration. Full-sample forecast RMS includes zero-risk months. Through-time comparisons use trailing 36-month gross realized volatility and RMS of forecasts over those same 36 months; net volatility is exported too. The first 35 months have no full trailing-window estimate.

Monthly limits are not intramonth guarantees. Execution at valuation endpoints, rolled-price percentage-return accounting and vendor data vintages remain unverified. No matched lecture replication or untouched holdout is claimed. Expanding risk estimates and true volatility targeting are future ideas only.

`run_research.py` is the single entry point. `sample_diagnostics.py` owns new calculations; `research_report.py` owns presentation. `backtest/engine.py` remains the shared accounting engine. Missing held returns produce a diagnostic report and CLI status 2, withholding full-period results. Synthetic tests and the archived 2000–2014 replay are recorded separately from current data readiness; see [validation](VALIDATION.md).

## Isolated endpoint sensitivity

`python scripts/run_research.py --endpoint-sensitivity` additionally evaluates the exact-date overlay in `config/endpoint_sensitivity.json`. It modifies a copy of the strategy return matrix, restoring only eight missing March/April 1997 cells from observed February 28 / March 27 / April 30 closes for DT, GS, LX and SS. It never writes to primary construction inputs. All forecasts and trading paths are recomputed using the same engine. This is an unverified data assumption, not a new strategy or a verified venue-calendar correction. Output snapshots, cost scenarios, class attribution and reports are isolated under `output/endpoint_sensitivity/` and `ENDPOINT_SENSITIVITY.*`. See [evidence and decision](ENDPOINT_DECISION.md).

## Covariance estimator comparison

`python scripts/compare_risk_models.py` re-runs the v2 strategy using the configured primary cost and band (now 2 bps and 10%) on endpoint-sensitivity returns with the 36-month window weighted by exponential decay (half-lives in `config/risk_model_comparison.json`), keeping the 0.5 correlation shrinkage, 2% floor and limits. The window and eligibility are unchanged, so only the covariance forecast differs. Results are in-sample on the 1976–2014 calendar.

**Historical results below: 5 bps, 10% band.** These saved estimates are retained as historical context. The [cost revision](../reports/cost_revision_20261026/SUMMARY.md) contains the refreshed 1 and 2 bps estimator tables. New comparison exports include cost/band columns and go into a specification-specific subdirectory of `reports/qps_baseline/output/risk_model_comparison/`, preserving the earlier table.

| Estimator | Trend Sharpe | Max drawdown | Turnover | Trend calibration | Static calibration |
|---|---|---|---|---|---|
| Equal weight 36m (current) | 1.071 | −14.5% | 7.4 | 1.27 | 1.41 |
| EWMA half-life 6m | 1.118 | −16.4% | 7.8 | 1.31 | 1.45 |
| EWMA half-life 12m | 1.096 | −15.4% | 7.5 | 1.26 | 1.40 |
| EWMA half-life 24m | 1.083 | −14.6% | 7.4 | 1.26 | 1.40 |
| Fast/slow (3m, equal) | 1.114 | −14.4% | 7.7 | 1.29 | 1.41 |
| Fast/slow (6m, 24m) | 1.103 | −15.2% | 7.6 | 1.27 | 1.40 |

Calibration is the std of gross return over forecast volatility (1.0 is calibrated). No estimator moves it: every one leaves trend and STATIC forecasts about 25–45% too low, so the shortfall is not the estimation window. Faster estimators raise trend Sharpe by 0.01–0.05 with slightly higher turnover, but this is a six-way in-sample choice with no significance test, so the 36-month equal-weight window stays.

Diagnostic, not adopted: with the baseline estimator, correlation shrinkage 0.1 instead of 0.5 lowers trend calibration from 1.27 to 1.10 and STATIC from 1.41 to 1.15 (trend Sharpe 1.085). Shrinkage toward zero correlation therefore explains much of the under-forecast. Walk-through and charts: [risk_model_estimators.ipynb](../notebooks/risk_model_estimators.ipynb).

## Trading-band experiment (Step 3)

The [fixed v2 band experiment](../reports/band_experiment_20261026/SUMMARY.md) compares 0%, 5% and 10% bands at both 1 and 2 bps, using the frozen Step 2 conditional inputs. The 10% band remains adopted. At 2 bps, removing the band raises annual mean return by 10.35 bps (CAGR by 8.38 bps), but the nominal paired 95% block-bootstrap interval for the mean difference is −11.19 to +31.03 bps per year. Sharpe declines from 1.092 to 1.076 and maximum drawdown deepens from −14.44% to −15.16%. The 5% gain is smaller. Neither candidate passes the frozen uncertainty screen.

The interval uses 20,000 circular moving-block resamples of paired monthly differences, with 12-month blocks and 6/24-month sensitivity checks. Family-adjusted intervals account for the eight reported candidate/cost/portfolio comparisons per block length, not the entire historical strategy search. All data remain inspected and conditional. Configuration and reproduction instructions are in `config/band_experiment.json` and the experiment package; `config/risk_config.json` retains its 10% primary band.

## Roll execution costs (Step 4; sensitivity only)

The [contract-data audit and sensitivity](../reports/roll_sensitivity_20261026/SUMMARY.md) found no delivery-contract IDs, expiry/roll schedules or adjustment lineage in the supplied files. A uniform quarterly/monthly calendar is therefore an explicit assumption, not inferred history. The production reference keeps 2 bps ordinary costs and the 10% band without an empirical roll schedule.

`RollSchedule` quotes 1 or 2 bps per unit of matched continuing notional for the **complete close/open**, equivalent to 0.5 or 1 bp per leg. Explicit per-leg quotes are also supported and converted. Same-direction overlap is `min(abs(previous), abs(executed))`, measured in beginning-month NAV units after carrying prior holdings forward. Ordinary changes cover the net resize; entries, exits and reversals add no roll overlap. A source switch supersedes a coincident assumed roll under the declared netted beginning-period execution convention. Economic carry and price adjustments are not charged as execution fees.

The limit solver includes ordinary and roll fees before sizing is finalized. Its proportional-scale objective remains monotone under the existing ordinary-cost bound: the new roll term is a nondecreasing `rate × min(scale × abs(proposed), abs(previous))`. Arbitrary nonlinear impact functions are not covered by this argument. Ledger and instrument/class attribution separate ordinary and roll fees and reconcile to total net return. Total one-way turnover includes two roll legs; ordinary and complete-roll rate bases must not be interchanged.

All 36 v2 TREND/STATIC scenarios were resimulated at regular costs of 1/2 bps with three quarterly phases and a monthly calendar. At ordinary 2 bps, TREND CAGR is 11.39% trade-only, approximately 11.21–11.30% for the quarterly assumptions and 10.85–11.12% for monthly assumptions. These are conditional in-sample sensitivity results, not verified all-in implementation returns. Actual roll-cost adoption awaits dated contract data and confirmation of the supplied series' adjustment and cost coverage.

## Liquidity and collateral feasibility (Step 5)

The [Step 5 assessment](../reports/implementation_feasibility_20261026/SUMMARY.md) uses each raw source separately. For holding month t, it excludes the latest bar before t and averages the preceding 20 recorded volume observations, keeping zeros. Incomplete/negative windows are invalid; history older than seven calendar days is flagged. These are descriptive screens, not eligibility changes. Source-close events use the previous source and source-open events the new source. Terminal liquidations are excluded from this beginning-decision audit. Reported volume units have not been verified as executable delivery-contract volume. NAV weights are never divided by these units to infer participation.

The workbook RF is a decimal monthly collateral-income proxy for January 2000–December 2014 only. Eight matched v2 runs (TREND/STATIC × 1/2 bps × zero cash/RF) start flat with earlier price history retained for forecast initialization and liquidate at the end. Collateral income equals RF × (1 − entry fees), in beginning-period NAV units. It enters realized P&L and subsequent drift, never current decisions. Costs and holdings are resimulated, so differences are not merely a fixed interest series added to an old NAV path. Income is a separate cash sleeve, not assigned to asset-class trading returns.

For comparability, the new table subtracts the same workbook RF once from both cash conventions when computing excess Sharpe. The separate zero-rate mean/volatility ratio uses unsubtracted returns; it matches the earlier reports' zero-cash statistic. Neither convention verifies actual collateral yield or the supplied return series' cost/interest coverage. No roll assumptions are added to these runs. Gross futures exposure is not a cash-loan balance. Capacity, margin and borrowing costs await AUM, dated contracts/multipliers/FX units, calibrated execution data, margin requirements and financing terms. No production strategy parameters change.

## Prospective evaluation freeze (Step 6 preparation)

The [prospective protocol](PROSPECTIVE_EVALUATION.md) freezes the current v2 candidate and original baseline/STATIC comparisons at 1/2 bps. It preserves the trade-only, zero-cash reference and the existing risk controls. A fixed 36-month calendar begins only after current data and a dated activation record are ready. Paired mean differences, drawdowns, costs, exposure and calibration are evaluated together; intermediate monitoring does not authorize retuning. The bootstrap intervals are descriptive given the short prospective sample, not a powered confirmation.

All available 1976–2014 history remains development evidence. Source/config snapshots and hashes detect changes relative to the recorded freeze; local hashes/timestamps alone do not prove external preregistration. Independent evaluation remains pending, and no paper-trading account or automated monitor has been started. The current idealized endpoint model is explicitly distinct from executable fills.
