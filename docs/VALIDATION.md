# Implementation and validation record — 8 October 2026

The code changes for the fixed 12-month strategy and extended-period presentation are implemented. A separately labeled March 1997 endpoint sensitivity now completes all 12 comparisons across the requested 468 months; its results are conditional on the unverified data assumption. **The preserved-policy 1976–2014 portfolio comparison remains data-blocked**, as required by the unchanged missing-held-return policy. This distinction is recorded in `output/risk/run_status.json` and both report formats.

## Completed checks

- **64 automated tests pass.** `output/risk/validation.json` records the test count, timestamp and current script/test/config hashes. Tests cover both successful synthetic execution of all 12 frozen portfolio comparisons and explicit blocking without partial performance publication.
- **12 original 2000–2014 runs reproduce** (trend/STATIC × no band/10% band × 0/5/10 bps). Every archived ledger column was compared; maximum absolute difference was approximately **4.00e-15**. References and hashes are in `output/legacy_2000_2014/`; the replay record is `output/risk/legacy_reproduction.json`.
- The full source rebuild audited 62 daily files and 457,155 rows. It reproduced all 20,987 supplied nonmissing monthly returns at stored precision and all 11,029 supplied blanks. The existing eight endpoint-supported research additions remain unchanged. Source hash checks passed.
- Prior-only signal/risk windows, source choice, future-data mutation and truncated-prefix replay checks pass. Missing held returns still raise explicitly. No current missingness changes current portfolio choices.
- Actual instrument costs include source close/open and final liquidation. Synthetic class net-return and cumulative P&L reconciliation, Euler forecast-risk reconciliation, after-cost exposure/risk limits and RF subtraction tests pass.
- Class statistics use the portfolio return series, apply prior eligibility/exclusions, and retain missing class history. If an eligible constituent return is unavailable, the entire class observation is missing rather than reweighted or zero-filled.
- Calendar-aware Spearman matched counts and slopes agree with direct calculations. HAC errors agree with the standard sandwich estimator on contiguous samples; the gap test confirms that missing months retain their calendar spacing.
- The five conditional PNG figures were visually inspected. The concise conditional HTML embeds all five; `docs/DATA_STATUS.md` is a short preserved-policy status note with no repeated figures. Local summary-report links resolve. Browser-level HTML layout verification was unavailable because computer access to Chrome was not approved.

## Data readiness findings

January 1976 has **seven** eligible instruments with complete prior estimation windows, versus the frozen minimum of ten. The date and threshold are unchanged; that month is flat under the existing rule. February 1976 is the first investable month. The report explicitly states the shortfall.

Every one of the 12 full-period portfolio attempts fails in **March 1997** on missing held returns for **DT, GS and LX**. Their March 27 close falls four days before the March 31 target and remains invalid under the existing three-calendar-day rule. The earlier venue audit left this exception unresolved. SS has the same endpoint gap but is not eligible then.

No full-period performance, alpha, drawdown, cost sensitivity or class-risk attribution table is published for the preserved-policy run. Those outputs are available in the separate conditional endpoint report. Old-period results were preserved in archives so they cannot be mistaken for the extended sample. The runner exports prior-eligible class statistics, eligible counts, rank autocorrelation, proposed endpoint values, blocking holdings and a clear data-status report, then exits with code **2**. Other exceptions remain errors.

The candidate eight March/April returns in `output/risk/proposed_endpoint_returns.csv` are **not applied to the primary dataset**. The conditional scenario applies the same eight returns to an isolated copy, with exact source prices and a change log. Verified venue/vendor evidence or an explicit decision to use a labeled research assumption is needed to resolve the blocker without silently changing the plan.

## Reproduction

```sh
python scripts/run_research.py --validate
python scripts/run_research.py
python scripts/run_research.py --full
python scripts/run_research.py --endpoint-sensitivity
```

The current `--validate` run succeeds. The default and full preserved-policy pipelines reach the documented missing-held-return blocker and return status 2. The full run also regenerates the separate historical EDA, clearly labeled as its original 2000–2014 analysis; the current report uses the new prior-eligible class definitions.

Pandas compatibility: audit tables now explicitly drop missing values after `stack()`, retaining the original flagged-observation behavior across pandas versions. This does not change return inputs or trading rules.

## Completed conditional sensitivity

`python scripts/run_research.py --endpoint-sensitivity` succeeds, while the primary run continues to record status 2 independently. The separate [report](../reports/qps_baseline/ENDPOINT_SENSITIVITY.md) and [HTML](../reports/qps_baseline/ENDPOINT_SENSITIVITY.html) present conditional results. Five new tests verify the narrow eight-cell overlay, input immutability, refusal to overwrite observed returns, exact-date pricing without fallback, and isolation from future raw-price changes. The original 12-run replay still agrees to approximately 4e-15.

The scenario keeps all 468 months, with January 1976 flat, and completes trend/STATIC × two bands × three costs. Class net contributions, instrument costs, Euler risk contributions and linked cumulative P&L reconcile; after-cost exposure and forecast-risk caps hold. Source input hashes remain unchanged. [Independent saved-output checks](../reports/qps_baseline/output/endpoint_sensitivity/data_validation.json) record reconciliation errors and scenario isolation.

The evidence note distinguishes public-holiday corroboration from unverified venue closure. The assumption has not been promoted into the preserved primary dataset. The five conditional figures are visually reviewed and the HTML is checked for embedded images and resolving local report links; no browser-level layout check is claimed.

## Midterm readability review

Lecture 6 slides 40–44 were reviewed as assignment reference material. The main conditional summary now follows the requested data, class statistics, autocorrelation, construction, results/benchmark, risk and improvements sequence. README and the preserved-policy status report are shortened; `CODE_GUIDE.md` summarizes architecture and `MIDTERM_GUIDE.md` provides a 15-minute walkthrough and a balanced strength assessment.

The additional stability table summarizes the existing ledger in four calendar blocks plus 2008 and an exclusion of 2008. It reuses the tested performance functions and does not change signals, positions, costs or model parameters. Block drawdowns reset their peak at block start; they do not restart the trading account or charge artificial liquidation. The noncontiguous exclusion reports mean/SD/Sharpe only, without a hypothetical CAGR or drawdown. None of these inspected historical blocks is an out-of-sample test.

The main presentation is now `REPORT.md` / `.html`, with the requested eight sections and timing table. `ENDPOINT_SENSITIVITY.*` remains a compatible copy; the unchanged preserved-policy blocker is documented in `docs/DATA_STATUS.md`.
