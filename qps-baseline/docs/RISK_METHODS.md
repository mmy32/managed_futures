# Fixed strategy and research definitions

The evaluation calendar is January 1976–December 2014. Earlier observations initialize the model; no start date or eligibility threshold is silently changed. January 1976 has seven eligible instruments, below the required ten, so the existing rule leaves both portfolios flat. March 1997 has missing held DT, GS and LX returns, which blocks the full-period comparison under the preserved endpoint policy. See [data status](DATA_STATUS.md), [presentation report](../REPORT.md) and [endpoint audit](ENDPOINT_REVIEW.md).

## Data, signal and eligibility

Retain the independently audited monthly endpoint construction and its eight documented corrections. Retain ND over EN and SP over ES/SC. Drop duplicate YM and unresolved EC identity. RL/ER form one column; switch permanently from RL to ER only after 36 consecutive ER monthly returns ending no later than t−2. Source dates precede holding months. Neither source choice nor eligibility uses current/future realized availability.

For holding month t, direction is sign(sum of returns t−12 through t−1). Volatility/correlation estimates use t−36 through t−1. Eligibility requires complete prior signal and risk windows and positive measured volatility; the portfolio is flat below ten eligible instruments. A zero signal is flat. Missing held returns raise an explicit error, including on final liquidation months. They are never filled, dropped or used to change the current portfolio.

The three-calendar-day endpoint freshness rule and bounded raw-date spans are preserved, along with the existing HS and Eurex exceptions. The unresolved March 1997 four-day endpoint gap is not automatically granted another exception. `proposed_endpoint_returns.csv` is review-only and is not consumed by any data loader.

## Risk and position sizing

Let sigma be monthly sample standard deviation × sqrt(12), floored at 2% annually. Let D be its diagonal matrix and R the sample correlation matrix from the common complete prior window. The annual covariance forecast is `Q = D (0.5 R + 0.5 I) D`. Ineligible rows/columns are zero. Positive shrinkage and the volatility floor make the eligible block positive definite.

Initial exposure magnitude is `0.40 / (eligible count × sigma)`. The trend signal supplies direction; STATIC is always long. Proportionally reduce the portfolio to satisfy `sum(abs(w)) ≤ 3` and `sqrt(w'Qw) ≤ 0.10`. Do not scale upward to reach the ceiling. STATIC uses its own all-long covariance forecast, so it need not match trend's absolute holdings. No equal class-risk allocation is imposed.

For actual carried holdings, same-direction positions within `target ± 0.10 abs(target)` are retained; otherwise trade to the nearest band edge. Entries, exits and reversals execute at target immediately. The common limit solver then reduces holdings if needed so `sum(abs(w))/(1−entry_fee) ≤ 3` and `sqrt(w'Qw)/(1−entry_fee) ≤ 0.10`. Risk limits override bands. Active comparisons are only band 0/10% and cost 0/5/10 bps. Earlier diagonal/class-balanced routines remain solely for compatibility and regression tests; the active runner evaluates only the frozen correlated model.

## Accounting and funding

Exposure is measured in units of beginning-month NAV. Same-source traded exposure is `abs(new−carried)`; a source switch charges `abs(new)+abs(carried)` to close/open the actual sources. Initial entry, drift-adjusted rebalancing and final liquidation are charged. Cost rate is bps/10,000. Gross return is the exposure/return dot product. Primary net return is gross less entry and liquidation costs, with RF = 0. Holdings carry as `w (1+r)/(1+net_return)`.

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

`run_research.py` is the single entry point. `research_statistics.py` owns new calculations; `research_report.py` owns presentation. `backtest.py` remains the shared accounting engine. Missing held returns produce a diagnostic report and CLI status 2, withholding full-period results. Synthetic tests and the archived 2000–2014 replay are recorded separately from current data readiness; see [validation](VALIDATION.md).

## Isolated endpoint sensitivity

`python run_research.py --endpoint-sensitivity` additionally evaluates the exact-date overlay in `config/endpoint_sensitivity.json`. It modifies a copy of the strategy return matrix, restoring only eight missing March/April 1997 cells from observed February 28 / March 27 / April 30 closes for DT, GS, LX and SS. It never writes to primary construction inputs. All forecasts and trading paths are recomputed using the same engine. This is an unverified data assumption, not a new strategy or a verified venue-calendar correction. Output snapshots, cost scenarios, class attribution and reports are isolated under `output/endpoint_sensitivity/` and `ENDPOINT_SENSITIVITY.*`. See [evidence and decision](ENDPOINT_DECISION.md).
