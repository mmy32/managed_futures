# GARCH correction verification

**PASS: 17/17 numerical checks passed.**

All observations in this package are explicitly synthetic. No uploaded monthly file or real daily futures history was fitted or scored. These checks verify code behavior; they do not establish a historical strategy advantage or validate actual market calendars.

Seed: 20261116. Runtime: 11.22 seconds. The short fixture uses a 12-month eligibility window and a six-month source-selection history to exercise actual production functions quickly. Production configuration and sealed reports are unchanged.

| Check | Result | Numerical evidence |
| --- | --- | --- |
| Missing GARCH dates advance expected variance | PASS | Maximum difference from the independent recurrence: 2.71e-20. |
| Missing observations differ from zeros and compressed time | PASS | See variance_trace.csv; counterfactual paths are illustrative failure modes. |
| DCC missing residuals use conditional second moments | PASS | Maximum error across fully/partly/unobserved cases: 0. |
| Unavailable DCC shocks do not become observed zeros | PASS | After 250 missing updates: fixed Q diagonal 1.000000; zero-shock counterfactual 0.600001. These are filter states, not portfolio returns. |
| GARCH rejects an unsuccessful optimizer | PASS | A scoped mock supplies success=False and a NaN objective. |
| DCC rejects an unsuccessful optimizer | PASS | A scoped mock supplies success=False and a NaN objective. |
| Real optimizer restored after failure checks | PASS | All later forecast fits call the actual SciPy optimizers. |
| RL risk uses ER after RL quotes end | PASS | 107 nonmissing synthetic ER risk returns remain after RL ends. |
| Lag 1: future mutation preserves earlier covariance | PASS | Maximum covariance difference through 2002-02: 0. |
| Lag 1: truncated history preserves earlier covariance | PASS | Maximum covariance difference through 2002-02: 0. |
| Excluded markets and their extra dates leave forecasts unchanged | PASS | Maximum covariance difference: 0; retained daily grids equal. |
| Lag 1: actual annual GARCH/DCC fits converge | PASS | Verified 1 annual refit(s), including January information timing. |
| Lag 1: retained forecast block is positive definite | PASS | Smallest eigenvalue across exported months: 0.00887365. |
| Lag 2: future mutation preserves earlier covariance | PASS | Maximum covariance difference through 2002-02: 0. |
| Lag 2: truncated history preserves earlier covariance | PASS | Maximum covariance difference through 2002-02: 0. |
| Lag 2: actual annual GARCH/DCC fits converge | PASS | Verified 2 annual refit(s), including January information timing. |
| Lag 2: retained forecast block is positive definite | PASS | Smallest eigenvalue across exported months: 0.00887365. |

## Inspect the calculations

- `variance_trace.csv`: expected variance after every date, alongside explicitly labeled zero-imputation and compressed-time counterfactuals.
- `dcc_missing_moments.csv` and `dcc_missing_state_trace.csv`: analytic conditional moments and the effect of 250 unavailable shocks on the DCC filter state.
- `source_continuation.csv`: selected ER risk returns remain available after RL ends.
- `fitted_parameters.csv`, `forecast_coverage.csv`, `forecast_covariances.csv`: actual SciPy estimates and production DCC forecasts on the synthetic fixture at both lags.
- `checks.csv` and `manifest.json`: machine-readable outcomes, seed, versions and hashes.

Missing-observation conditional moments and the 21-day covariance forecast remain modeling approximations. Real-data conclusions still require original daily prices, calendar/source verification, corrected historical replay and independent evaluation.

To reproduce from the project root, choose a new directory:

```sh
PYTHONPATH=. .venv/bin/python scripts/verify_garch_fixes.py --output reports/garch_verification_new
```
