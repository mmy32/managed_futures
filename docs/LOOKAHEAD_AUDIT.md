# Original-period timing audit and OOS assessment

**Scope note (7 October 2026):** The empirical figures below describe the archived 2000–2014 evaluation. The current 1976–2014 run stops on missing held DT/GS/LX returns in March 1997; its timing comparison is not published. Synthetic causal tests still pass. See the current [report](../reports/qps_baseline/REPORT.md) and [validation status](VALIDATION.md).

The implementation has past-only signal, risk and trading rules under the stated monthly endpoint convention. That is not a certificate that the vendor dataset or same-close fills are historically executable.

## Issue found and corrected

The old source mapping chose RL or ER using the **current month's** available realized return. The simulator passed the resulting source-switch flag to the fee-aware position policy. That let contemporaneous return metadata influence current position sizing; the prior tests covered forecasts but did not cover this whole path. It also assumed an RL→ER continuation was known in advance without an as-of record.

The strategy now uses a separate, deterministic source rule: retain RL until ER has 36 consecutive monthly returns available through at least t−2, then use ER permanently. This switches in **2006-01**, before RL's later disappearance, without consulting that disappearance or current-period P&L. The change affects 35 monthly RL-column returns. [Exact changes](../reports/qps_baseline/output/timing_audit/source_rule_changes.csv) preserve the comparison with the original reproduced/research returns. Source labels are defined independently of missing realized P&L. The original CSV reproduction is untouched.

Policy-aware source costs now require known-at dates strictly before the holding month; missing or future dates raise an error. The source rule itself is implemented and tested from prior observations. The label column alone is not treated as proof of historical availability. The fixed source-choice policy is shared by all risk variants and never fitted to their performance.

## What is checked

- Signals, eligibility, volatility and covariance use t−1 or earlier; each forecast exports its actual information cutoff. No full-sample volatility, centered window or future-completeness filter enters trading.
- Source choice uses only observations through t−2. Current realized missingness cannot trigger a favorable source fallback; a missing held return fails explicitly.
- Band decisions use carried holdings, past-derived targets and covariance, and predetermined cost/source information. Current realized returns enter P&L only after those decisions.
- Future-data mutation tests cover the entire pipeline across three risk models and three band settings, including executed positions and prior P&L. Prefix replay reproduces the full-run history without access to its future. Terminal liquidation is disabled for replay so a changed artificial end date does not create a false mismatch.
- Missing calendar rows and zero information lags are rejected. Existing checks cover accounting, after-cost limits and the nine original baseline/cost runs.

[Validation record](../reports/qps_baseline/output/risk/validation.json) lists the current test count and code hashes. [Source schedule](../reports/qps_baseline/output/construction/strategy_source_schedule.csv) and [audit summary](../reports/qps_baseline/output/timing_audit/summary.json) record the timing evidence.

## Performance after the correction

The current baseline result is 9.05% annual arithmetic mean, 9.86% volatility, and -15.82% worst drawdown at 5 bps. Alpha against matching STATIC is 8.57%, with a 95% HAC interval [3.59%, 13.55%]. See the refreshed [brief report](../reports/qps_baseline/REPORT.md).

Using one additional full month of signal/risk delay gives **7.28% mean, 9.24% volatility and -15.69% drawdown**. This is a conservative timing sensitivity, not a realistic next-session fill simulation. It does not remove the assumption of executing the monthly rebalance at the valuation endpoint; that remains unverified.

## How promising is it?

Worth further research, but insufficient to predict good OOS performance. Positive results across nearby parameter choices and a simple trend signal are encouraging. However, risk forecasts underestimate realized fluctuations, the trading-band cost saving is modest, execution/funding conventions are idealized, and the 2000–2014 sample has been examined repeatedly. Positive in-sample HAC alpha does not account for all strategy-selection bias and does not guarantee future profits. STATIC is only one benchmark; alpha against it does not establish unique skill relative to other trend strategies.

[Subperiods](../reports/qps_baseline/output/timing_audit/subperiods.csv), including an exclusion of 2008, are descriptive stability checks. **None is a fresh OOS test.** Repartitioning already-inspected years does not make them untouched. The extra-delay comparison is also a sensitivity, not OOS.

Freeze this corrected specification, obtain unexamined post-2014 data with documented roll/FX/contract conventions, run the fixed model once, and then monitor a forward paper-trading period. Evaluate risk calibration, costs and drawdowns alongside returns; do not select the best parameters after seeing the holdout. The current data cannot supply that evidence.

## Remaining limits on a no-lookahead claim

The source vendor's vintage-adjusted price history and point-in-time instrument universe are unavailable. Retrospective calendar corrections and fixed metadata exclusions are documented, but cannot independently certify the data as it would have appeared in real time. Back-adjusted futures prices can change earlier percentage returns when later rolls occur. No code-only test can rule that out without vendor methodology or archived vintages. Same-endpoint decisions/fills need next-session execution accounting to validate live feasibility.

Independent research supports the broad trend-following idea, not this exact implementation: [Hurst, Ooi and Pedersen, A Century of Evidence on Trend-Following Investing](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf). Repeated model selection can inflate backtest evidence: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

Reproduce: `python scripts/run_research.py`, `python scripts/audit_timing.py`, and `python -m pytest -q` from the project directory.
