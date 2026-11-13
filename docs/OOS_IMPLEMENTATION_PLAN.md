# Out-of-sample preparation plan

Pause for confirmation after each step. The working copy is based on GitHub commit `65edd98`.

1. **Working copy and inputs — complete.** An isolated checkout contains the latest committed
   source and 65 hash-verified historical inputs; previous research artifacts were preserved.
2. **Matched comparison — complete.** Inverse-volatility sizing is the baseline, HRP within each
   class is the enhancement, and both use the same baseline-derived risk-rescale shadow.
3. **Timing audit and fixes — complete for the inspected code.** Causal endpoint construction,
   fail-closed rescaling, synthetic full-path checks and an in-sample lag sensitivity are recorded
   in [HRP_TIMING_AUDIT.md](HRP_TIMING_AUDIT.md). Vendor vintages and execution remain unresolved.
4. **Out-of-sample runner — implemented; released-data validation pending.** The runner applies the fixed comparison
   to a declared calendar, validates inputs, uses sufficient prior warmup, and writes matched
   ledgers and results. It must use the causal strategy-input path, not retrospective RL/ER or
   full-file-span reconciliation. Include the one- and two-month information-lag cases as labeled
   sensitivities, and fail on missing held returns or inconsistent provenance. Do not score the
   new period until settings, dates, starting state and interpretation are declared.
5. **End-to-end validation — historical checks complete; release checks pending.** The independent
   accounting, prefix and future-data-mutation checks and the historical coverage limitation are
   recorded in [OOS_VALIDATION.md](OOS_VALIDATION.md). When the release arrives, validate its
   schema, coverage, timestamps, vendor conventions, provenance and compatibility with warmup.
   A same-close fill remains an assumption until suitable execution data support it.
6. **Repository cleanup — complete in the isolated checkout.** Removed caches and four
   regenerable `reports/qps_baseline/*.html` renderings; their Markdown reports and charts remain.
   Fixed active links and marked the older QPS comparison and backlog as historical. The other
   eight HTML files are retained because sealed release manifests include them. No source inputs,
   research records, frozen releases or original-checkout changes were removed.

   The four removed renderings are listed in the cost revision's historical provenance record;
   their original bytes can be restored, if needed for that audit, with `git restore
   --source=65edd98 -- 'reports/qps_baseline/*.html'`. They can also be regenerated, although a
   regenerated rendering is not guaranteed to match the archived byte hashes.
7. **Code summary — complete; README update deferred.** [CODE_SUMMARY.md](../CODE_SUMMARY.md)
   describes the data-to-P&L architecture, main functions, assumptions and run commands. Per the
   user's request, update the README after the out-of-sample data has been used.

The historical HRP Sharpe advantage reversed under a two-month information lag. Keep that
development result visible; do not reinterpret it as fresh out-of-sample or next-session evidence.
