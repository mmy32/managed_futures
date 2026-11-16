# GARCH and full-sample data remediation

Monthly full-sample update: the user confirmed that the professor's daily 2014 endpoint and
monthly May 2025 endpoint are intentional. The new [monthly implementation](MONTHLY_FULL_SAMPLE.md)
uses only the supplied monthly workbook and asset map, fits GARCH at monthly frequency and
completes all four 593-month portfolio comparisons on the approved 48-market coverage-conditioned
universe. [Read the results](../reports/monthly_full_sample_20261116/SUMMARY.html).
The strict all-market diagnostic still stops on unknown held returns. The daily-model evidence
and limitations below describe that separate frequency specification; post-2014 daily files are
not required to run this monthly specification.

Status updated: 16 November 2026. All 65 original inputs now match their recorded hashes: the
asset map, historical monthly CSV, benchmark workbook and 62 daily instrument files. Those daily
files contain 457,155 observations collectively spanning January 2, 1969–December 31, 2014.
The additional full-sample monthly workbook extends through May 2025, but the post-2014 daily
extension remains absent. Current verification includes actual historical annual GARCH fits and
daily/monthly reconciliation; these are model/data diagnostics, not regenerated full-period
strategy performance or independent out-of-sample evidence. Archived report packages, notebook
outputs and source snapshots retain their original assumptions. See [VERIFYING_RESULTS.md](VERIFYING_RESULTS.md)
for the current readable verification output and commands. The November 15 code-verification
record belongs to its earlier source/run and is separate from the November 16 verification.

## Findings and disposition

| Finding | Source repair | Remaining evidence |
| --- | --- | --- |
| 1. Historical risk used raw RL after monthly returns had switched to ER. | Research loaders and the matched runner share prior-only source selection and use the selected source's own daily returns. Price levels are never divided across RL and ER. | Rebuild the historical comparison with original inputs; the old 1976–2014 results do not measure this corrected policy. |
| 2. The full period depends on unverified March 1997 endpoints; the newer wider replay also encounters an HS January 2006 endpoint gap. | Preserve causal endpoint freshness and missing-held-return failures. No automatic calendar exception, fill or performance-dependent sample deletion is added. | Obtain venue calendars, source identity and vendor price conventions before deciding whether an endpoint exception is justified. Code cannot establish those facts. |
| 3. DCC-GARCH was selected after many trials without a convincing incremental gain. | Keep its status explicit as a configured research candidate; preserve simpler-model comparators and distinguish development diagnostics from independent validation. | Compare fixed rules on genuinely unseen data. A source repair or new split of inspected history cannot establish an empirical edge. |
| 4. Missing daily observations were compressed during fitting, filled for up to five rows during return construction, and replaced by zero innovations during DCC filtering. | Daily return construction preserves unknown observations. GARCH/DCC fitting and filtering retain observation-grid time and use conditional missing-observation moments rather than fictitious observed zero shocks. | A common observation grid still needs verified session/availability conventions; conditional moment imputation is a model assumption, not observed prices. |
| 5. Excluded EC/YM still influenced pooled risk estimation. | Apply declared strategy exclusions to the risk-estimation universe, including the shared shadow calibration. | Verify every retained instrument's identity/classification and predeclare the universe before scoring new data. |
| 6. Failed GARCH/DCC optimizer results were accepted. | Require successful, finite, feasible fits and surface failures instead of silently accepting returned parameters. | Rerun with original inputs and retain fit diagnostics; there is no historical convergence-impact estimate without that run. |

The implementation regression checks use synthetic inputs and file fixtures. The current
verification also checks the restored original inputs and actual historical GARCH fits. Current
results belong to the current source; historical test counts in report packages belong to their
saved source versions. Passing these checks does not settle the performance or provenance questions.

Implementation verification on 15 November 2026: `.venv/bin/python -m pytest -q` passed all
331 tests; `.venv/bin/mypy src` passed for 64 source files; `git diff --check` passed.
Ruff introduced no findings relative to the HEAD versions of touched Python files; existing
repository lint findings remain. Those November 15 checks used synthetic data and file fixtures;
the original course inputs were unavailable at that time. No archived report, notebook result
or raw input was rewritten. Consult the current verification package for the new run's results.

Current verification on 16 November 2026 passed 379 automated tests, type checks, 17 synthetic
numerical checks and 15 selected real-data historical GARCH checks. All 65 original input hashes
match; daily-to-monthly reconstruction has zero missing-state or stored-precision mismatches.
The package's 56 output hashes, 66 input hashes and source/configuration hashes were verified
after generation. [Read the results](../reports/research_verification_20261116/SUMMARY.html).
This is not a completed full-period strategy backtest or post-2014 OOS assessment.

## Full-sample interpretation

The saved risk notebook searched roughly 40 variants on January 1976–December 2014. Its cached
5-bps, inverse-volatility comparison at 0.1 shrinkage reports DCC-plus-rescale Sharpe 1.171 versus
1.110 for monthly covariance plus rescale. The paired 90% interval for the +0.061 difference is
−0.011 to +0.156; it includes zero before accounting for the wider search. Unscaled DCC's
TREND calibration is 1.170 versus 1.095 for the monthly estimator. These are historical
observations from [the saved notebook](../notebooks/risk_model_estimators.ipynb), not updated
performance of the repaired source or a reason to claim DCC superiority.

Annual GARCH/DCC parameters are estimated on expanding **past** daily history. The 36-month
configuration is an eligibility requirement, not a rolling 36-month parameter fit. The January
refit information-lag defect was fixed before this remediation; that is separate from searching
many specifications on the same development sample. The trailing risk rescale uses past shadow
portfolio observations, not a constant fitted to the final full-sample calibration statistic.
Calibration restores missing calendar slots before rolling and delaying its scale, so a
60-month window and a two-month lag retain their stated units across zero-risk gaps.

Excluded and undeclared markets are removed before constructing the daily observation grid,
not only before fitting. A date supplied solely by an excluded source cannot change another
market's adjacent-price returns. True missing quotes and the first ratio after such a gap
remain unknown; the code does not assign a multi-session price move to one observed day.

Whole-history CPCV can select using training months later than its held-out months. A 36-month
embargo also does not isolate an expanding GARCH fit or a 60-month calibration history. The
default hold-stage selection diagnostics therefore use chronological prior-only selection;
any retained CPCV is explicitly exploratory. Neither changes the status of already-inspected
history into an untouched evaluation. Use the locked matched runner for independent assessment
after recording data provenance, access history and the evaluation calendar.

The original paper-style TSMOM path also used full-panel quality/correlation cleaning and silently
zero-filled unknown held returns. Its repaired runner uses the static audited identities from
`config/tsmom_baseline.json`, reconstructs causal endpoint returns from raw daily prices, requires
prior signal/EWMA eligibility and fails on missing held returns. It deliberately keeps raw RL
for both returns and volatility, with no fallback or source averaging. This is distinct from
the final matched inverse-volatility/HRP comparison, where both arms share the RL/ER source rule.
New TSMOM output requires a new directory; archived zero-filled results are not overwritten or
silently presented as results of the repaired policy.

## Required data and next work

All original files have been restored without changing their contents; the additional monthly
workbook is preserved separately:

```text
data/raw/
├── AssetMapCsv.csv
├── MonthlyReturns.csv
├── Lecture3_livedata.xlsx
├── MonthlyReturns_FullSample.xlsx
└── futures_underlying/
    ├── AN.csv
    ├── ... all 62 original daily instrument files, including RL.csv and ER.csv
    └── ZZ.csv
```

All 65 original supplied files match the recorded raw-input hashes. The full-sample workbook has
676 months, February 1969–May 2025, and does not supply daily prices or resolve the March 1997/HS
January 2006 blanks. Its
post-2014 history has availability gaps, including AP, SS and ZD; audit these without scoring
or choosing a replacement strategy from the outcomes. Vendor
vintage, continuous-contract adjustment method, timezone, source-availability convention,
delivery-contract identities and exchange calendars are also needed where available. An unknown
fact must remain labeled unknown. Do not create replacement prices or infer a trading calendar
from an advantageous performance outcome.

The restored daily inputs now support direct arithmetic reconciliation and actual historical
GARCH fitting. Fit/covariance diagnostic checks do not report strategy P&L. A corrected strategy
comparison must retain one fixed historical calendar and the same source, eligibility, costs
and limits; record convergence, source, missing-data and accounting
diagnostics. Keep the failed status if a held endpoint remains unresolved. Export into new
directories and compare both historical arms under the same repaired code. Any necessary data
convention change needs a dated explanation and a new source/configuration snapshot.

Compatible daily prices for the post-2014 extension are still needed before evaluating the
configured DCC-GARCH strategy on the new monthly period. Do not invent them from monthly returns.
Then prepare genuinely unseen released data or an activated prospective evaluation using
[OOS_RUNNER.md](OOS_RUNNER.md). The new inputs need compatible historical warmup and declared
availability/execution conventions. Do not bridge missing years with fabricated returns. Old
freeze hashes continue to identify old source versions; they do not certify the repaired source.
The [historical validation record](OOS_VALIDATION.md) remains evidence for the saved runner
version and identifies the full-sample and endpoint limitations that still require data.
