# Timing audit for the matched HRP comparison

This audit covers the comparison components and synthetic tests completed for the inverse-volatility
baseline and HRP enhancement. It does not certify the future data, live fills, or independent
out-of-sample performance.

| Status | Area | Evidence and remaining limitation |
| --- | --- | --- |
| Safe in tested code | Signals and sizing | Signals and risk forecasts use the configured positive lag; HRP receives those positions and covariance, not current realized returns. |
| Safe in tested code | RL/ER choice and trades | Source selection uses a prior window; the simulator chooses positions before reading that month's return. Source availability dates remain a data-provenance assumption. |
| Safe in synthetic replay | DCC-GARCH, rescale and HRP | For one- and two-month lags, future-data mutation and truncated-history replay leave earlier source choices, forecasts, targets, executed positions and P&L unchanged. Tests include the January annual refit and both comparison portfolios. |
| Fixed in strategy path | Month-end endpoints | The strategy rule now uses the latest close available by the anchor subject to freshness; later file rows cannot determine acceptance. The old full-file-span rule is retained as `historical_span_endpoints` solely for reproducing and auditing the supplied historical monthly file. It is retrospective and must not be used for strategy inputs. |
| Fixed in risk path | Missing shadow returns | The rescale shadow now stops on a missing held return instead of falling back to an unscaled model for all months. The historical research runner records a blocked status; no complete comparison is published by that run. |
| Compromised for trading, isolated | Historical RL/ER fallback | `construct_returns.assemble` fills RL from ER using the same month's availability for retrospective reconstruction. The current strategy loader replaces both RL returns and its source schedule using a prior-only rule; the reconstruction schedule must not be used as a trading input. |
| Suspect: data provenance | Prices and universe | Point-in-time vendor vintages, back-adjustment policy, instrument history and source-availability timestamps are not established. Freshness alone does not prove a venue was open or a contract remained tradable. Verify the released data before relying on it. |
| Suspect: execution | Same-endpoint fill | The backtest assumes a target based on the prior endpoint can be executed at that endpoint. A two-month information lag is an information-delay sensitivity, not evidence of an executable next-session fill. A separately defined next-session convention requires the necessary data and accounting. |
| Development evidence only | Selection and resampling | HRP was selected using previously inspected 1976–2014 history. Historical bootstrap and cross-validation results are not untouched out-of-sample evidence, and the retrospective reconciliation rule is not a trading rule. |

`tests/data_processing/test_endpoints.py` covers the formerly unstable March 2024 boundary,
stale prices and future-only observations. `tests/backtest/test_hrp_timing.py` covers the
matched pipeline at both lags. `tests/data_processing/test_strategy_inputs.py` checks that
the loader replaces the retrospective RL values. `tests/backtest/test_hrp_comparison.py` and
`tests/backtest/test_research_spec.py` cover missing-held-return failure handling.

The historical supplied-data reconciliation and the saved research return panel were checked
in memory after the change; their values matched, and their archived files were not rewritten.
The pending out-of-sample runner must still validate the new files and their availability,
declare its evaluation calendar and warmup, and keep the fixed comparison settings.

## Historical information-lag sensitivity

Using the fixed matched comparison, the conditional 1976–2014 development panel, DCC-GARCH,
the 10% band and 2-bps ordinary trade costs:

| Information lag | Portfolio | Annual net mean | Volatility | Sharpe | Max drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 month | Inverse-vol baseline | 11.07% | 9.23% | 1.199 | -11.64% |
| 1 month | HRP | 11.19% | 8.47% | 1.321 | -10.13% |
| 2 months | Inverse-vol baseline | 7.35% | 9.18% | 0.800 | -23.78% |
| 2 months | HRP | 6.73% | 9.48% | 0.710 | -35.65% |

The historical HRP Sharpe advantage reverses under the longer information lag. The lag changes
the information available to signals, risk estimates, eligibility and rescaling; the result is
not an isolated execution-cost effect. These are inspected in-sample results, conditional on the
unverified March 1997 endpoints and idealized endpoint fills. Lag two delays information by an
entire month and does not simulate an actual next-session execution.

A later [historical runner validation](OOS_VALIDATION.md) used a shorter development window and
the new RL/ER daily risk construction. Its results are not directly comparable to this table and
also show that the HRP advantage is sensitive to the information lag.

The [metrics and ledgers](../reports/hrp_timing_sensitivity_20261113/), input-manifest hash,
raw-file verification count and source hashes are saved separately from the earlier research
packages. The source snapshot in that directory matches the hashes recorded for the run;
subsequent runner work changed the daily loader. Reproduce with that snapshot and the verified
historical inputs from a project root with the required dependencies using
`PYTHONPATH=. python scripts/audit_hrp_lag.py --output <new-output-directory>`; the command checks
the recorded historical inputs and refuses to overwrite an existing output directory.
