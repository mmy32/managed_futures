# Out-of-sample runner validation

The historical checks are complete; the instructor's released data have not been received or
validated. These checks do not establish independent out-of-sample performance.

| Area | Status | Evidence or next action |
| --- | --- | --- |
| Historical inputs | Checked | All 65 frozen input hashes match. The 59 required daily files pass the runner's ISO-date, ordering, uniqueness and price checks. Hashes confirm identity, not point-in-time provenance. |
| Retrospective paths | Safe in inspected runner | The runner constructs causal endpoints and the RL/ER schedule directly from daily prices; it does not load the retrospective reconstruction. |
| Accounting and matching | Passed on a restricted historical replay | A separate calculation reproduced every case's gross P&L, source-switch trades, ordinary costs, NAV and headline metrics. Calendars and position limits matched. The shadow supplied 37 and 36 prior nonflat observations at lags 1 and 2. |
| Future-data dependence | Passed in tested replays | A 2012-12 prefix and an alteration of later prices left earlier source choices, targets, exposures, diagnostics and ledgers unchanged for both strategies and lags. Prices changed in 58 files and all four cases' later monthly returns changed. Existing synthetic tests also compare full covariance matrices. |
| Historical coverage | Blocked for the wider replay | The 2004–2014 replay stopped at a held HS return in January 2006. Its last January close is January 27, four calendar days before the January 31 anchor; the fixed rule permits three. The [endpoint review](ENDPOINT_REVIEW.md) documents corroborating Hong Kong holiday evidence, but the runner does not automatically grant an exception. |
| Vendor history and execution | Suspect; release review pending | Vendor vintage, contract/roll adjustment, availability timestamps and executable fills remain unverified. One- and two-month lags are information delays; neither establishes a next-session fill. |
| Estimation universe | Review before scoring | The example lists 58 historical markets. EC and YM are excluded from positions but still enter risk-model fitting when included in the declared universe. EC's identity/classification is unresolved; decide and record the estimation universe before examining performance. |

The completed replay uses **2009-04 through 2014-12**, with a shadow beginning 2006-03. It
starts after the known HS gap solely to exercise the unmodified endpoint rule; this is not a
performance-selected or untouched sample. A temporary validation copy changed only the
development-end guard from 2014-12 to 2009-03 so the production runner could process historical
dates. Strategy, risk and cost settings remained unchanged. The production guard was not
changed. The [checks and outputs](../reports/oos_historical_validation_post_gap_20261113/) and
the [failed wider replay](../reports/oos_historical_validation_20261113/) are retained.

For context only, the restricted replay gives:

| Information lag | Zero-rate ratio, baseline / HRP | HRP minus baseline annual net mean | Annual turnover, baseline / HRP |
| --- | ---: | ---: | ---: |
| 1 month | 0.641 / 0.827 | -43.61 bps | 9.36× / 13.66× |
| 2 months | 0.655 / 0.609 | -142.35 bps | 9.39× / 13.55× |

The shorter sample, flat starting positions, endpoint rule and RL/ER daily risk construction
differ from the conditional 1976–2014 lag analysis in [HRP_TIMING_AUDIT.md](HRP_TIMING_AUDIT.md).
In particular, the older risk path used raw RL daily returns after the monthly source had
switched to ER; the new runner uses ER's own daily returns while ER is selected. The original
RL series ends in 2008. Neither result proves HRP will improve out-of-sample performance. In
this restricted replay, HRP has a higher risk-adjusted ratio only at lag 1, with higher turnover
and lower net mean at both lags.

When the upload arrives, before scoring:

1. Confirm the evaluation dates are genuinely beyond all development data used, fix the universe
   and conventions, and record provenance and prior access. The example dates are placeholders.
2. Verify schemas, instruments, per-market coverage and historical warmup, vendor vintage,
   timezone, availability and continuous-contract adjustments. Establish compatible historical
   and new prices without an undocumented splice.
3. Investigate endpoint gaps and market calendars without choosing repairs or dropping markets
   based on realized performance. The runner must stop on unknown held returns.
4. Review the idealized endpoint execution and cost assumptions; only claim executable fills if
   suitable prices and an independently specified execution rule support them.
5. Prepare a new hash-verified declaration, inspect it, then run both predeclared lag cases and
   check their matched ledgers. Preserve any failed status instead of presenting partial results.

The historical replay is reproducible with `PYTHONPATH=. python scripts/validate_oos_history.py
--output <new-directory>`. Its temporary mutated prices are regenerated by the script; each
preparation's source snapshot and input hashes are preserved.
