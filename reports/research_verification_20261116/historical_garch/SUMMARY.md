# Historical DCC-GARCH integration verification

**PASS: 15/15 checks passed.**

These calculations use the restored original daily futures prices, not synthetic observations. They verify risk-model estimation, missing-data handling, source consistency and causality on inspected historical data through December 2014. No strategy portfolio was scored and no post-2014 observation was fitted or evaluated.

The monthly workbook is explicitly loaded in decimal units and restricted through 2014-12. Its RL column is replaced by the same prior-only source rule used by the strategy; all other supplied monthly observations and missing cells are preserved. No March 1997 or Hong Kong endpoint overlay is applied.

Forecasts use the configured 36-month eligibility window, 2% annual volatility floor and DCC shrinkage. These are covariance forecasts before portfolio-level shadow rescaling; the diagnostic does not simulate holdings, trades or performance.

Runtime: 103.31 seconds. Original daily files matched: 62/62.

| Check | Result | Evidence |
| --- | --- | --- |
| Original daily inputs match the frozen reference | PASS | 62/62 original daily CSV hashes match; no raw input is modified. |
| Unavailable daily quotes remain unknown | PASS | 236,014 unavailable quote intervals inspected; none was assigned an observed or zero return. |
| ER supplies risk returns after original RL terminates | PASS | RL's last quote is 2008-12-10; 1,521 subsequent ER risk returns retained. |
| Excluded/unused markets and their extra dates cannot change risk returns | PASS | Perturbed excluded/unused price levels and an excluded-only Saturday; the complete retained risk-return panel is identical. |
| Actual pooled GARCH and DCC annual fits converge | PASS | 2 fitted annual models; diagnostics include optimizer objectives, iteration counts and elapsed fitting time. |
| EC and YM are excluded before parameter estimation | PASS | 56 retained estimation series; excluded markets absent from every fitted annual parameter set. |
| Actual lag-1 future mutation preserves earlier forecasts | PASS | Independent estimation/filtering; maximum covariance difference through 2014-02: 0. |
| Actual lag-1 truncated history preserves earlier forecasts | PASS | Independent estimation/filtering; maximum covariance difference through 2014-02: 0. |
| Lag 1, 2014-01: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 7.18228e-05. |
| Lag 1, 2014-02: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 8.03787e-05. |
| Lag 1, 2014-12: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 7.11163e-05. |
| Lag 2, 2014-01: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 6.83378e-05. |
| Lag 2, 2014-02: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 7.18228e-05. |
| Lag 2, 2014-12: active covariance is positive definite | PASS | 56 eligible markets; minimum eigenvalue 7.92363e-05. |
| Input and implementation hashes remain unchanged | PASS | Input files are immutable; hashes are checked before and after the calculations. |

## Declared historical forecast dates

| Lag | Holding month | Information through | Eligible markets | Median annual volatility | RL annual volatility |
| --- | --- | --- | --- | --- | --- |
| 1 | 2014-01 | 2013-12 | 56 | 15.49% | 15.41% |
| 1 | 2014-02 | 2014-01 | 56 | 15.21% | 17.68% |
| 1 | 2014-12 | 2014-11 | 56 | 16.82% | 16.12% |
| 2 | 2014-01 | 2013-11 | 56 | 13.24% | 14.36% |
| 2 | 2014-02 | 2013-12 | 56 | 15.49% | 15.41% |
| 2 | 2014-12 | 2014-10 | 56 | 18.18% | 22.14% |

## Inspect or reproduce

- `input_inventory.csv`: all input hashes and daily-file identity checks.
- `fitted_parameters.csv`: actual annual estimates, convergence and timing.
- `daily_gap_audit.csv` and `RL_ER_continuation.csv`: unknown intervals remain unknown; the selected source supplies its own returns.
- `forecast_covariances.csv`, `forecast_summary.csv`, `forecast_coverage.csv`: forecast values and observed/missing daily history counts.
- `monthly_eligibility_inputs.csv`: the historical monthly input panel actually used.

Missing-observation Gaussian conditional moments and the 21-day covariance forecast remain modeling approximations. Passing these historical integration checks does not validate vendor vintages, executable fills, every historical month, strategy performance, or an independent out-of-sample advantage.

Choose a new directory to rerun from the project root:

```sh
PYTHONPATH=. .venv/bin/python scripts/verify_historical_garch.py --output reports/historical_garch_new
```
