# Lecture 9 portfolio-construction experiment

Development selection for the next period: **gamma20**. Production defaults are preserved.

Primary scores cover 1986-2014 after ten years of calibration history; all history is development data.
The primary case uses a two-month information lag and 1.5 bps per absolute one-way turnover.

| Policy | Net annual mean | CAGR | Volatility | Max drawdown | Annual turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| band10 | 8.54% | 8.48% | 8.65% | -12.42% | 9.39x |
| full | 8.55% | 8.47% | 8.89% | -12.71% | 11.42x |
| gamma5 | 7.59% | 7.48% | 8.46% | -12.00% | 5.91x |
| gamma10 | 8.10% | 8.00% | 8.70% | -11.63% | 7.36x |
| gamma20 | 8.33% | 8.24% | 8.82% | -11.99% | 8.58x |
| walkforward | 8.54% | 8.47% | 8.68% | -12.95% | 9.33x |

| Comparison with bands | Gross change (bps/year) | Cost saving | Net change |
| --- | ---: | ---: | ---: |
| full | 4.36 | -3.04 | 1.32 |
| gamma5 | -100.08 | 5.23 | -94.85 |
| gamma10 | -47.08 | 3.05 | -44.03 |
| gamma20 | -21.73 | 1.23 | -20.51 |
| walkforward | -0.33 | 0.09 | -0.24 |

See `configured_lag2/paired_intervals.csv` for paired 6/12-month block intervals and family-adjusted intervals.
Selection scores use only prior completed months; the walk-forward path carries actual holdings across switches.
The fixed-gamma comparisons and selection remain exploratory because these years were already inspected.

`common_risk/` replays the two original paths' ex ante directions at the same after-fee forecast risk, with new trades and NAV.
`configured_lag1/` and `rolling_reference_lag2/` evaluate the primary-selected fixed policy without retuning.
`rolling_reference_lag1/reference_reproduction.json` checks the archived 2-bps baseline.

Results remain conditional on the unverified March 1997 endpoints and vendor price-history conventions.
This is a zero-cash, trade-only monthly proxy; contract rolls, executable fills and capacity are not established.

The source/config release is sealed in `freeze.json` and `source_snapshot.zip`. No untouched evaluation data were supplied; independent validation remains pending.
