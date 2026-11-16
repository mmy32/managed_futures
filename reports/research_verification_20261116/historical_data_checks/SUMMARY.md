# Original supplied-data verification

Historical arithmetic audit only. historical_span_endpoints uses full-file date spans, and the reconstructed RL/ER fallback uses the current month's availability. These retrospective conventions reproduce the supplied file; they are NOT trading inputs, an out-of-sample assessment, or verified executable futures P&L.

**Status: passed**

Checked 62 daily files and 457,155 observed positive, finite closes, spanning 1969-01-02 through 2014-12-31.

The supplied monthly panel contains 552 months and 58 markets. Its full calendar and all missing cells were retained during reconstruction.

Missing-state mismatches: **0**. Observed values outside stored precision: **0**. Maximum absolute difference: 4.66e-08.

Tolerance is min(5e-8, half the final stored CSV digit) + 1e-12; stored zero uses 1e-12. No unknown return is replaced by zero.

Vendor review flags: **1**. Flags do not alter data or certify field meaning. See [OHLC review flags](ohlc_review_flags.csv).

All original-input identities and unchanged bytes are recorded in [input hashes](input_hashes.csv); [checks](checks.csv) and [per-market reconciliation](reconciliation.csv) provide the detailed results.

These daily inputs end in 2014. This audit does not provide post-2014 daily data, select an evaluation period, fit a strategy or compute performance.
