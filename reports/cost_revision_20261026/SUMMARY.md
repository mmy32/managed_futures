# Step 2: controlled transaction-cost comparison

Completed 26 October 2026. **Primary cost: 2 bps; sensitivity: 1 bps. Step 3 has not started.**

Lower assumed trading costs improve net returns modestly. They do not change the signals, the 36-month risk estimator or the adopted 10% trading band. The results remain in-sample and **conditional on the unverified March 1997 endpoint assumption**. The preserved-policy runs still fail on missing held returns.

## What was run

The original 65 input files were restored byte-for-byte from the team's local course-data folder: asset map, monthly returns, benchmark workbook and 62 daily files. Each matches its historical manifest hash. Monthly reconstruction matches the saved research panel. The optional source ZIP is absent; its extracted daily files are verified.

The existing 1976–2014 baseline and v2 configurations were reproduced first: 24 historical runs at 0/5/10 bps, including both bands and both strategies. All 30 file comparisons (ledgers, metric tables, alphas and return panels) pass numerical tolerances; the largest absolute difference is 2.21e-13. [Reference checks](reference_reproduction/checks.json).

The new controlled grid has **32 runs**: baseline/v2 × TREND/STATIC × 0/1/2/5 bps × 0/10% bands. All use the same 468 months, data scenario, signals and risk rules. Every path was resimulated, including fee feedback into NAV, carried holdings and limits. Costs are charged per unit of absolute one-way traded notional / beginning-period NAV; turnover is not halved.

## Main results at the adopted 10% band

| Portfolio | Cost (bps) | CAGR | Net Sharpe | Max drawdown | Annual direct cost drag |
| --- | --- | --- | --- | --- | --- |
| BASELINE TREND | 1 | 11.09% | 1.081 | -15.76% | 0.064% |
| BASELINE TREND | 2 | 11.02% | 1.075 | -15.77% | 0.127% |
| V2 TREND | 1 | 11.47% | 1.099 | -14.43% | 0.074% |
| V2 TREND | 2 | 11.39% | 1.092 | -14.44% | 0.148% |
| Matching STATIC | 1 | 5.18% | 0.487 | -55.90% | 0.007% |
| Matching STATIC | 2 | 5.17% | 0.486 | -55.91% | 0.014% |

STATIC is identical across the two versions and is shown once. CAGR is compounded growth; direct cost drag is 12 times mean monthly booked costs, not the difference between gross and net CAGR.

For v2 TREND, moving from 5 to 2 bps raises CAGR from 11.15% to 11.39% and Sharpe from 1.071 to 1.092. Annual direct cost drag falls from 0.370% to 0.148%, a saving of 22.23 bps of NAV per year. At 1 bps, CAGR is 11.47% and direct drag is 0.074%.

The baseline/v2 ranking is descriptive: the FX blend was selected after inspecting this history. Lower costs do not supply independent evidence for the signal choice.

## V2 class contributions at 2 bps

| Class | Gross annual mean contribution | Annual cost contribution | Net annual mean contribution |
| --- | --- | --- | --- |
| COMM | 6.225% | 0.059% | 6.166% |
| EQ | 1.633% | 0.008% | 1.625% |
| FI | 1.701% | 0.036% | 1.665% |
| FX | 1.960% | 0.044% | 1.916% |

These contributions sum to the portfolio's arithmetic mean and costs. They are not class CAGRs. [Both versions and both 1/2 bps cases](output/class_cost_comparison.csv).

## Risk-estimator sensitivity, with the cost cases held explicit

The existing six-estimator diagnostic was refreshed at 1 and 2 bps, retaining its original window, shrinkage, signals and 10% band. These are additional exploratory runs, separate from the 32-case controlled grid.

| Estimator | TREND Sharpe, 1 bps | TREND Sharpe, 2 bps | Drawdown, 2 bps | Calibration, 2 bps |
| --- | --- | --- | --- | --- |
| equal_36m | 1.099 | 1.092 | -14.44% | 1.272 |
| ewma_hl6 | 1.147 | 1.140 | -16.20% | 1.312 |
| ewma_hl12 | 1.125 | 1.118 | -15.24% | 1.260 |
| ewma_hl24 | 1.112 | 1.105 | -14.50% | 1.255 |
| fast_slow_3_equal | 1.144 | 1.136 | -14.20% | 1.288 |
| fast_slow_6_24 | 1.132 | 1.124 | -15.04% | 1.269 |

Calibration is the SD of gross returns divided by their prior forecast volatility; 1 is ideal. Faster estimators still underpredict risk and do not dominate on drawdown. Keep the existing equal-weight 36-month estimator. This is an inspected six-way in-sample comparison, not a new validation or an adopted enhancement. [Full TREND/STATIC table](output/risk_model_comparison/cost_comparison.csv).

## Validation and qualifications

- **140 tests passed** against the final source snapshot. Every new run reconciles gross return plus cash income minus costs to net return, linear charges to actual turnover, and NAV to compounding. No rebalance risk/gross-limit breaches occur. Class contributions reconcile at both 1 and 2 bps. [Checks](output/cost_validation.json).
- All 65 raw files and all 241 historical report/output files remain unchanged. Reference manifests, source hashes and execution logs are preserved separately in this release.
- The 12-run 2000–2014 replay mentioned in older reports is a historical validation record; its archived input configs are absent, so it was not rerun here. This release independently reproduces the full 1976–2014 baseline/v2 reference.
- Regular expiry-roll activity, calibrated spread/impact and executable endpoint fills remain unresolved. The 1–2 bps charge is an aggregate assumption, not a fitted execution model.
- The FX description now correctly states that opposite signs produce zero exposure; half exposure requires one zero sign. No signal calculation changed.

## Files and next step

- [V2 presentation report](REPORT_V2.md) · [standalone HTML](REPORT_V2.html)
- [Baseline presentation report](REPORT.md) · [standalone HTML](REPORT.html)
- [All 32 scenarios, including gross/net metrics](output/cost_comparison.csv)
- [Baseline preserved-policy status](supporting_docs/DATA_STATUS.md) · [v2 status](supporting_docs/DATA_STATUS_V2.md)
- [Provenance](provenance.json) · [Reproduction instructions](REPRODUCE.md)

**Stop here.** Step 3 will test the predeclared 0/5/10% bands at 1 and 2 bps. The 5% strategy experiment has not been run or adopted.
