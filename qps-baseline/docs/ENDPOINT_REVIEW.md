# Monthly endpoints and anomaly verification

**Stage snapshot:** this review preceded reconstruction. The subsequent [research report](../REPORT.md) documents the separately published research dataset, eight calendar-supported return additions, refreshed EDA and completed backtest. Lecture 4 now confirms the inputs are already rolled; the exact adjustment method remains unspecified. The findings below retain the original supplied-data comparison.

Reviewed 6 October 2026. **The supplied monthly file is reproducible to its stored numeric precision:** all 20,987 observed returns and all 11,029 blanks match one inferred rule, including the RL/ER continuation. This resolves the endpoint behavior empirically; it does not prove the original implementation or certify the vendor's adjusted prices. No source prices, monthly returns, or EDA outputs were replaced.

## Inferred reproduction rule

1. Target the **last Monday–Friday date of each month**, without an exchange-holiday calendar. Every date label in `MonthlyReturns.csv` follows this convention.
2. Only generate targets **within the raw instrument's first-to-last observation dates**. In particular, do not extend the target grid beyond the final raw date.
3. At each target, take the most recent observed Close on or before it, provided its age is **at most three calendar days**. This includes the target and the three preceding calendar dates. It is not a three-business-day rule.
4. Calculate `current endpoint Close / previous calendar month's endpoint Close - 1`. Both adjacent endpoints must be valid. Do not skip a missing month or forward-fill a missing monthly return.
5. For RL, use its own monthly return when available; otherwise use ER's independently calculated monthly return. This fills exactly **73 months, December 2008–December 2014**. Do not divide an ER price by an RL price. The supplied pre-continuation RL returns match RL itself. Other retained columns match their same-ID raw source under this test; that does not establish all historical duplicate-selection intentions.

This rule is suitable as a specification for **reproducing the supplied file**. A version using actual exchange sessions would deliberately differ and should be separately named and reconciled.

Evidence: [rule comparison](../output/endpoint_review/rule_comparison.csv), [instrument-level comparisons](../output/endpoint_review/rule_comparison_by_instrument.csv), [endpoint evidence](../output/endpoint_review/endpoint_evidence.csv), and [RL/ER continuation](../output/endpoint_review/rl_er_continuation_evidence.csv).

### Why these choices matter

All rows below include the same RL-first, ER-fallback diagnostic.

| Alternative | Supplied returns it misses | Values it adds where the supplied file is blank |
|---|---:|---:|
| Calendar month-end, three calendar days, bounded targets | 74 | 0 |
| Last weekday, one calendar day, bounded targets | 728 | 0 |
| Last weekday, two calendar days, bounded targets | 588 | 0 |
| **Last weekday, three calendar days, bounded targets** | **0** | **0** |
| Last weekday, three calendar days, allow targets after raw end | 0 | 6 |
| Last weekday, four calendar days, bounded targets | 0 | 10 |
| Last weekday, three weekdays, bounded targets | 0 | 10 |
| Last observed price without freshness limit, bounded targets | 0 | 26 |

Among jointly observed values, every tested variant matches within the audit tolerance. Availability distinguishes the variants. The selected rule's maximum absolute difference is **4.66e-8 decimal return units**, or approximately **0.000466 basis points**. All differences are consistent with the precision of each stored CSV token, including small negative returns written with three significant digits in scientific notation. Per-cell rounding tolerances are exported; this is not a claim of bit-for-bit equality.

The blanks comprise 10,997 leading-history/first-return cells, 26 internal gaps caused by invalid adjacent endpoints, and six terminal gaps. See [blank classification](../output/endpoint_review/blank_classification.csv).

## Specific anomalies and their disposition

### ER on 28 May 2012: settlement convention supported, row not independently certified

The raw Close of 820.45 lies below Low 822.16 and repeats 25 May's Close. ICE's contemporaneous notice says stock-index products traded a shortened session on 28 May and settlements would ordinarily repeat the prior trading day's settlement, except after a significant move. Thus, a settlement-valued Close can legitimately lie outside that day's traded range. The notice supports this explanation; the vendor's definition of `Close` and the duplicated volume/open interest remain unverified. [ICE notice, 1 May 2012, page 1](https://www.ice.com/publicdocs/futures_us/exchange_notices/exnot2012MemDay_revised.pdf)

**Disposition:** retain the row with a field-convention flag. Do not clip Close to Low or substitute a trade price. The date is not a monthly endpoint; the May endpoint is 31 May, so retaining or omitting this interior observation does not change the endpoint ratio. This does not establish that dropping the row would be acceptable for daily analysis.

### AP in July 2014: missing observations, not an exchange-wide holiday explanation

ASX's official July report records **23 ASX futures/options trading days**, explicitly covering SPI 200 contracts. July has 23 weekdays. AP contains only **19 July observations**, absent on **4, 25, 28, and 29 July**. The earlier audit highlighted only the three-day consecutive gap; this review adds 4 July. Given AP's supplied Australian-equity mapping, the omissions are inconsistent with treating those dates as exchange-wide holidays. Vendor instrument identity and the missing prices still require confirmation. [ASX July 2014 activity report, page 3](https://www.asx.com.au/content/dam/asx/about/media-releases/2014/ASX-Group-Monthly-Activity-Report---July-2014.pdf)

**Disposition:** retain four explicit missing-session flags. Do not create prices by carrying forward or interpolating. June and July endpoints are present, so the supplied July monthly return still reconciles. Daily volatility and path-dependent calculations remain affected. See [missing dates](../output/endpoint_review/ap_missing_july_sessions.csv).

### Six December 2014 omissions: verified closure plus inferred truncation behavior

Eurex's 2014 calendar confirms **31 December was closed for all derivatives**. AX, DT, UB, UZ, XU, and XX end on 30 December. Their last weekday target is 31 December, which falls outside each file's observation range. The inferred bounded-target rule therefore excludes it even though the prior day's price is fresh. This exactly explains all six terminal blanks. [Eurex 2014 calendar, page 2](https://deutsche-boerse.com/resource/blob/249120/6fadad3fe12a3cc3fa392442532d4414/tradingcalendar_2014_en-data.pdf)

**Disposition:** preserve the blanks when reproducing the supplied file. A future exchange-calendar version should evaluate 30 December as the legitimate final session and report the six changed results separately. The original code is still needed to establish whether the truncation was intentional.

### HS in January/February 2006: holiday gap corroborated

Hong Kong's official 2006 holiday list identifies 30 and 31 January as Lunar New Year holidays. HKEX's 2006 fact book reports **19 January trading days for Hang Seng Index futures**, matching the raw HS file's 19 observations. The final January observation is 27 January; its age relative to the Tuesday 31 January target is four calendar days, so the inferred rule rejects it and makes both January and February returns missing. [Hong Kong Government holiday notice](https://www.info.gov.hk/gia/general/200504/15/04150111.htm), [HKEX Fact Book 2006, printed page 190](https://www.hkex.com.hk/-/media/hkex-market/market-data/statistics/consolidated-reports/hkex-fact-book/hkex-fact-book-2006/fb_2006)

**Disposition:** treat the January end-date gap as consistent with scheduled holidays, not a missing-price error. Preserve the two supplied blanks for reproduction; a calendar-aware revision would assess them separately.

### March/April 1997: endpoint mechanism resolved; historical venue closure not fully verified

DT, GS, LX, and SS end March at 27 March, four calendar days before the Monday target of 31 March. Rejecting that endpoint explains **eight** missing March/April returns. A contemporaneous UK council calendar identifies 28 and 31 March as Easter holidays, corroborating the date pattern, but it does not establish the exact 1997 futures-venue schedule. [Contemporaneous public-holiday calendar, appendix 10](https://docs.east-ayrshire.gov.uk/crpadmmin/JUNE96/JUNE%2096/POLICY%20AND%20RESOURCES%20COMMITTEE%20-%2013%20JUNE%201996.pdf)

**Disposition:** record the holiday explanation as corroborated but not fully venue-verified. Preserve the supplied blanks; do not invent daily bars.

### SS at year-end 1991–1998: unresolved source-specific coverage

SS has eight year-end intervals totaling **57 absent weekdays**. On **32** of these dates both GS and LX have raw observations. This evidence rules out explaining the whole pattern as a common closure across those supplied UK series, although it does not independently prove SS traded on every date. SS's stale December endpoints explain **16** missing December/January returns; together with its two March/April 1997 gaps, this accounts for all 18 internal SS gaps.

**Disposition:** preserve the gaps and request vendor lineage or contract-level history. The peer evidence is in [ss_year_end_peer_evidence.csv](../output/endpoint_review/ss_year_end_peer_evidence.csv). Do not reuse another instrument's prices to fill SS.

### Repeated OHLC: confirmed repetition, price correctness unresolved

The seven repeated-OHLC runs remain unverified. Variable volume/open interest confirms these are not simply duplicate full rows, but cannot prove the prices are genuine. Only three runs contain accepted endpoints, affecting **four existing monthly returns**:

| Raw run | Endpoint | Existing monthly returns depending on it |
|---|---|---|
| FN, 26 February–5 March 1975 | February 1975 | March 1975 |
| FN, 28 May–5 June 1975 | May 1975 | May and June 1975 |
| DA, 30 September–3 October 1997 | September 1997 | October 1997 |

FN's February return and DA's September return are already missing because no valid previous monthly endpoint exists. The other three FN runs and UZ's 20–25 February 2008 run do not contain selected endpoints. [Full endpoint impact](../output/endpoint_review/repeated_ohlc_endpoint_impact.csv)

**Disposition:** retain all seven run flags and mark these four returns for sensitivity analysis. Do not modify Close, infer a replacement from neighboring prices, or certify the suspect values without independent data. Ordinary repeated-close runs in EC/SS also remain flagged; this review does not convert them into confirmed errors.

## What is ready, and what remains

The reproduction endpoint specification is ready and validated. The source-quality investigation is **partly resolved**: public records explain holiday/settlement behavior, but they cannot supply missing AP/SS prices or authenticate historical repeated OHLC values. Vendor identity, roll/adjustment methodology, and original lecture code have not been supplied.

Before publishing a corrected return dataset, obtain that provenance and resolve or explicitly document the remaining flags. Reproduction should retain the original availability pattern. Any approved calendar corrections or exclusions should be versioned separately and accompanied by a change log. No reconstructed return matrix or backtest was generated in this step.

## Reproduce this review

```bash
python scripts/review_endpoints.py
```

The script regenerates diagnostic CSVs and `output/endpoint_review/summary.json`. It checks three-day boundary behavior, weekend anchors, terminal truncation, adjacent-month missingness, stored-value precision, and input SHA-256 preservation. The narrative and external-source judgments are reviewed snapshots, not automatically regenerated. Primary source PDFs are retained in `output/endpoint_review/sources/`; the source register records URLs, relevant pages, and hashes.
