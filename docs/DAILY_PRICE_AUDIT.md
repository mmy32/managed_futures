# Daily futures price audit

Current implementation status: [research report](../reports/qps_baseline/REPORT.md). This audit's original flag counts are preserved; the research dataset now includes separately logged calendar corrections and the EDA/backtest have been completed.

Follow-up: [monthly endpoint and anomaly verification](ENDPOINT_REVIEW.md) resolves the empirical endpoint rule and updates the ER, AP, HS, and December 2014 interpretations below. This original audit remains a snapshot of the initial flags.

Audit date: 6 October 2026. Inputs: 62 files in `data/FuturesUnderlyingData`, the instrument map and supplied monthly returns. The audit now recomputes the original outlier and missing-month lists directly from supplied returns, independently of the refreshed EDA. The raw files contain 457,155 observations, collectively spanning 2 January 1969 to 31 December 2014. Source files were not modified.

**Result:** all 127 previously flagged monthly returns reconcile to raw month-end close ratios. One row violates the supplied OHLC bounds. Calendar gaps, repeated prices, and missing monthly endpoints need targeted review before reconstruction. An extreme return or repeated close alone is not evidence of an erroneous price.

This audit supersedes the earlier EDA's statement that raw prices, volume, and open interest were unavailable. Contract-level identifiers, expiry dates, roll flags, adjustment documentation, and verified exchange calendars remain unavailable.

| Area | Result | Assessment |
|---|---|---|
| Structural checks | All files have ordered, unique dates and six numeric, finite, populated fields. No weekend observations, nonpositive OHLC prices, or negative volume/open interest. | Passes these checks; absent trading sessions are assessed separately. |
| OHLC consistency | One inconsistent row: ER, 28 May 2012. | Vendor verification required. |
| Extreme observed close changes | 458 flags: 259 at least 10% in absolute size; 258 with absolute robust z-score at least 10. These sets overlap. | Review flags, not deletion candidates by default. |
| Large move followed by reversal | 15 flagged observations across 11 instruments. | Inspect neighboring prices; no bad tick is confirmed from reversal alone. |
| Calendar gaps | 16,469 absent weekday/instrument observations in 15,124 intervals; 88 intervals contain at least three absent weekdays. | Weekdays include holidays and exceptional closures; these are not counts of confirmed missing trading sessions. |
| Unchanged closes | 219 runs of at least four recorded observations across 14 instruments. | EC accounts for 126 runs and SS for 50. Seven runs repeat all OHLC values; none repeats every field throughout the run. |
| Monthly outlier reconciliation | 127 of 127 match last-observed closes in the immediately previous and current calendar months. | Maximum absolute discrepancy: approximately 4.92e-10 in decimal return units. This verifies arithmetic, not vendor price accuracy or investable returns. |
| Internal missing monthly returns | All 26 have raw prices in both adjacent months; every pair has at least one endpoint more than three calendar days before month-end. | Consistent with an endpoint freshness rule; original construction code is needed to establish the rule. |
| Six missing December 2014 returns | AX, DT, UB, UZ, XU, XX each have 19 December observations through 30 December. | Raw data did not end in November. End-of-series/month labeling logic needs investigation. |

## Priority findings

### 1. ER has a close below the supplied daily low

On **28 May 2012**, ER reports Open 823.77, High 829.35, Low 822.16, and Close **820.45**. The close, volume (83,570), and open interest (442,335) exactly repeat the preceding observation on 25 May, while Open and Low change. This is an internal inconsistency if the four fields describe the same price basis and session. A settlement-versus-trade-range convention is also possible and cannot be resolved from these files.

**Action:** verify the vendor's field definitions and original row before editing anything. Preserve the row and its flag. ER is an additional raw series, absent from the existing 58-column monthly file, so it must be reviewed before any ER/RL merging is reproduced.

Evidence: [issue row](../reports/qps_baseline/output/daily_audit/price_issues.csv) and [neighboring observations](../reports/qps_baseline/output/daily_audit/price_review_context.csv).

### 2. Calendar gaps require different explanations

- **AP, 25, 28, and 29 July 2014:** only AP is absent on each date; all 60 other active raw series have observations. The next AP observation is 30 July, up 0.832% from 24 July. This isolated gap warrants checking the source and the relevant exchange calendar. Cross-market availability alone does not establish that AP traded.
- **SS, year-end 1991–1998:** eight intervals omit seven or eight weekdays. The longest is 23 December 1997 to 5 January 1998, with eight intervening weekdays. Repeated year-end gaps explain 16 missing December/January returns. This pattern warrants checking the vendor's historical coverage and the exchange calendar.
- **DT, GS, LX, SS, March/April 1997:** the last March price is 27 March, four calendar days before month-end. The resulting eight missing returns occur in March and April even though both months have daily data.
- **HS, January/February 2006:** January ends at 27 January, four calendar days before month-end, corresponding to the two missing returns.
- **AX, DT, UB, UZ, XU, XX, December 2014:** data ends on 30 December, only one calendar day before month-end. These six trailing gaps are not explained by the same greater-than-three-day endpoint pattern.

No calendar gaps have been filled. A price change across an absent session is labeled as spanning a gap, rather than assumed to be a one-session return.

Evidence: [long gaps with peer availability](../reports/qps_baseline/output/daily_audit/long_gap_review.csv), [all gap intervals](../reports/qps_baseline/output/daily_audit/calendar_gaps.csv), [weekday peer coverage](../reports/qps_baseline/output/daily_audit/weekday_absence.csv), [internal monthly gaps](../reports/qps_baseline/output/daily_audit/monthly_missing_trace.csv), and [trailing monthly gaps](../reports/qps_baseline/output/daily_audit/trailing_missing_trace.csv).

### 3. Repeated closes are concentrated, but usually not repeated records

EC and SS account for 176 of 219 unchanged-close runs. The longest EC runs have **15 observations** each: 9–30 April 2014 and 20 October–7 November 2014. DA has a 12-observation run in September 1997. Positive volume is reported on every observation in **215 of the 219 runs**, so unchanged closes cannot generally be interpreted as zero trading activity.

Seven runs repeat all OHLC fields: five FN runs during February–June 1975, one DA run from 30 September to 3 October 1997, and one UZ run from 20–25 February 2008. The five FN runs and the DA run also have Open = High = Low = Close throughout. Volume and/or open interest vary, so these are not identical full-record repetitions. These seven runs deserve priority review for price-field replication, limited price precision, or other source conventions; the audit cannot select an explanation.

The files also contain **730 zero-volume observations** and **2,590 zero-open-interest observations**, including 2,088 in SS. These are stored numeric zeros, not blanks. Their interpretation should be verified before volume or open interest becomes a filtering or strategy input.

Evidence: [unchanged-close runs](../reports/qps_baseline/output/daily_audit/stale_runs.csv) and [instrument inventory](../reports/qps_baseline/output/daily_audit/inventory.csv).

### 4. Large daily moves remain review flags

| Instrument | Date | Observed close change |
|---|---|---:|
| ZU | 17 January 1991 | -31.89% |
| SP | 19 October 1987 | -28.61% |
| JO | 11 October 1991 | +26.99% |
| KC | 27 June 1994 | +26.15% |
| JO | 9 October 1998 | +25.51% |

Of 458 flagged observations, **24 span at least one absent weekday**. They should not be treated as directly comparable one-session moves until calendars are verified.

The robust-score rule is relative to each instrument's full-sample median absolute deviation. It flags 111 EC observations despite absolute moves of only approximately **0.30%–1.28%**, and 43 SS observations with absolute moves of approximately **0.22%–2.35%**. Low typical variability makes these statistically unusual within their series; they are not large absolute-price-change errors by definition.

The reversal screen identifies an absolute move of at least 10% followed by an opposite move that brings the two-observation net return within 20% of the initial move's magnitude. It finds **15 observations**, including EN and ND on the same date, so the flags are not independent events. As one example, ZO rises 11.09% on 30 March 2005 and falls 11.25% on 31 March. Both closes fall inside their daily ranges and volume increases markedly, so the supplied data does not establish a lone erroneous close.

Evidence: [all extreme flags, next observations, and reversal labels](../reports/qps_baseline/output/daily_audit/extreme_moves.csv), with [neighboring rows for reversal candidates](../reports/qps_baseline/output/daily_audit/price_review_context.csv).

### 5. Monthly outliers are supported by the supplied daily paths

Each of the 127 existing flags was traced individually. **All 127 reconcile**, and none overlaps an unchanged-close run of four or more observations or a gap of three or more absent weekdays within the flagged month. Forty-seven contain at least one daily extreme flag; the remaining 80 accumulate their monthly move without crossing the daily screen.

| Monthly example | Previous month-end close | Current month-end close | Monthly ratio | Largest absolute daily move in month |
|---|---:|---:|---:|---:|
| ZO, June 1988 | 1,318.72 on 31 May | 2,557.14 on 30 June | +93.91% | 7.26% |
| ZI, March 1980 | 36,038.20 on 29 February | 18,891.80 on 31 March | -47.58% | 4.99% |

These two extreme months reflect cumulative changes in the supplied daily series rather than a single very large daily jump. No monthly outlier was removed, winsorized, or labeled a confirmed error. Matching endpoints cannot verify adjustment factors, contract rolls, currency conventions, or collateral income.

Evidence: [127 endpoint reconciliations](../reports/qps_baseline/output/daily_audit/monthly_outlier_trace.csv) and [daily context for every flagged month](../reports/qps_baseline/output/daily_audit/monthly_outlier_daily_context.csv).

## Method and reproduction

Run from the project folder:

```bash
python scripts/audit_daily.py
```

The script uses the existing pandas/numpy dependencies and exports diagnostics under `output/daily_audit/`. This report is a reviewed snapshot; the script regenerates its supporting tables and summary, not this narrative.

- Observed close change: `Close[t] / Close[previous recorded observation] - 1`, without forward-filling.
- Extreme screen: absolute close change >= 10% **or** absolute robust z-score >= 10, using each instrument's full-history median and `1.4826 × MAD`. This is retrospective quality screening, not a trading signal or significance test.
- Calendar screen: Monday–Friday dates strictly between recorded observations. No exchange holidays are removed. Leading/trailing coverage is kept separate from internal gaps.
- Unchanged-close screen: at least four consecutive recorded observations with exactly equal closes. The count includes the first price, so four observations represent three unchanged transitions. Calendar gaps can occur between these recorded observations.
- Monthly trace: the last raw close available inside each of two adjacent calendar months, without merging instruments or carrying a close across a wholly absent month. Absolute matching tolerance is `5e-8` in decimal returns (0.0005 basis points).
- Verification: the saved monthly flags and internal-gap keys are checked against current monthly data. SHA-256 hashes of all audit inputs are checked before and after the run. Exact input hashes are exported in [source_manifest.csv](../reports/qps_baseline/output/daily_audit/source_manifest.csv); counts and thresholds are in [summary.json](../reports/qps_baseline/output/daily_audit/summary.json).

## Recommended disposition

1. **Keep source data intact and retain all flags.** Prioritize the ER row, AP's isolated gap, SS's year-end gaps, and the seven repeated-OHLC runs for vendor/calendar verification.
2. **Resolve monthly endpoint rules next.** Check the apparent three-day freshness condition and separately investigate the six December 2014 omissions. Do not silently fill either set of monthly gaps.
3. **Reconstruct returns only with documented merge and adjustment conventions.** The 127 successful outlier reconciliations support the supplied arithmetic, but do not certify the full return series or determine how EN/ND, ER/RL, ES/SC/SP, and YM/ZD should be handled.
