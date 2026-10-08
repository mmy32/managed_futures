# Historical 2000–2014 EDA — separate from the current presentation

This is the retained historical EDA, with its original 2000–2014 sample and available-instrument methodology. It is not the new prior-eligible 1976–2014 class analysis. This report uses the separately logged research return dataset. Strategy results and remaining implementation limitations are in [current report](../REPORT.md).

## Data and audit status

There are 552 months (January 1969–December 2014), 58 instruments, and 20,995 observed returns. The original CSV's 20,987 returns and 11,029 blanks were reproduced at stored precision. Eight returns were added only to the research version after exchange-calendar verification; original raw files remain unchanged. [Construction changes](../output/construction/return_changes.csv) and [endpoint review](ENDPOINT_REVIEW.md) document every exception.

The raw audit examined 62 files and 457,155 daily rows. It found 458 extreme-move flags, 219 repeated-close runs (at least four observations), seven repeated-OHLC runs, and one OHLC inconsistency. These are review flags, not proven price errors. All 127 previously flagged monthly extremes trace to the raw monthly closes. See [daily audit](DAILY_PRICE_AUDIT.md) and [unresolved issues](../output/construction/unresolved_issues.csv).

The research data retains 24 internal monthly gaps: SS has 18; DT, GS and LX have two each. The verified HS January/February 2006 gaps and six December 2014 early endings are resolved in this version. No missing return is filled with zero; no outlier is winsorized. EC retains its supplied FX label for descriptive EDA, while the strategy excludes it pending identity verification. YM and ZD remain in EDA so their near-duplicate exposure is visible; the strategy retains ZD only.

![Coverage](../output/eda/coverage.png)

## Monthly mean and standard deviation

The main comparison sample is 180 months, January 2000–December 2014. [Instrument statistics](../output/eda/instrument_stats.csv) include explicit monthly mean/std and all-history statistics. Class returns below average available instruments within each month; membership changes. They are descriptive averages, not the volatility-scaled strategy.

| Class | Monthly mean | Monthly std | Annual mean | Annual vol |
|---|---:|---:|---:|---:|
| COMM | 0.341% | 4.068% | 4.10% | 14.09% |
| EQ | 0.231% | 4.714% | 2.77% | 16.33% |
| FI | 0.282% | 1.126% | 3.39% | 3.90% |
| FX | 0.131% | 1.871% | 1.57% | 6.48% |

Annual mean = 12 × monthly mean; annual vol = sqrt(12) × sample monthly std. Annualization does not correct for autocorrelation. The 54-instrument complete-sample sensitivity in [class statistics](../output/eda/class_stats.csv) is selected ex post and must not define a tradable universe. Different all-history samples should not be used for unqualified instrument rankings.

## Cumulative returns

The class chart includes additive cumulative returns (the lecture convention), compounded indices and compounded drawdowns. Instrument plots provide both 1 + cumulative sum and cumulative product of 1 + returns. Each contiguous observed segment is rebased independently; missing months are not bridged. Compounding is an illustrative price-return index until the vendor's futures P&L denominator is verified.

![Class return summaries](../output/eda/class_summary.png)

- [Instrument plots, page 1](../output/eda/instrument_cumulative_01.png)
- [Instrument plots, page 2](../output/eda/instrument_cumulative_02.png)
- [Instrument plots, page 3](../output/eda/instrument_cumulative_03.png)
- [Instrument plots, page 4](../output/eda/instrument_cumulative_04.png)
- [Instrument plots, page 5](../output/eda/instrument_cumulative_05.png)

[Instrument cumulative values](../output/eda/instrument_cumulative_segments.csv) preserve segment identifiers.

## Correlations

The Pearson matrix uses at least 60 overlapping observations per pair, with [overlap counts](../output/eda/correlation_overlap.csv). Average signed within-class pairwise correlation is 0.348; across-class correlation is 0.054. YM/ZD correlation is 0.999968. Pairwise deletion can produce a non-positive-semidefinite matrix; this exploratory matrix is not used for portfolio optimization.

![Correlations](../output/eda/correlation.png)

## Autocorrelation and horizons

Lecture pp. 25–26 discuss rank autocorrelation of monthly returns. The primary [autocorrelation table](../output/eda/autocorrelation.csv) therefore compares monthly returns at calendar lags 1–12, with both Pearson and Spearman estimates and matched-pair counts. The intact calendar is shifted before missing pairs are dropped; ranks are computed on the matched sample. Mean lag-one Spearman correlations by class are COMM: -0.001, EQ: 0.049, FI: 0.071, FX: 0.066.

To also address aggregated horizons, [horizon statistics](../output/eda/horizon_statistics.csv) and [block returns](../output/eda/horizon_returns.csv) report 1-, 3-, 6-, and 12-month non-overlapping compounded returns, anchored at January 2000. A block requires every underlying monthly observation. These include block mean/std and lag-one correlations between blocks. Annual blocks provide only 15 observations, so estimates are especially uncertain. Monthly lag tables require at least 60 matched pairs; block autocorrelations require at least eight. No pooled t-statistics or significance claims are made across the many dependent comparisons.

![Dependence](../output/eda/dependence.png)

## Benchmarks and limitations

The supplied workbook matches all 180 comparison months. SG Trend has annualized mean 7.75% and volatility 14.60%, consistent with lecture p9. [Benchmark comparisons](../output/eda/benchmark_comparison.csv) are descriptive return gaps and correlations, not regression alpha. The current strategy report implements HAC alpha but withholds the extended-period estimate while missing held returns block evaluation. No bond series is supplied for a literal 60/40 benchmark.

Lecture p14 confirms that daily prices are already rolled. The exact roll adjustment, currency conversion, collateral convention and executable contract accounting remain unspecified. Raw prices, volume and open interest are available; actual roll dates and execution cost history are not. Retaining source values is not certification of their economic accuracy.

## Reproduce

```sh
python scripts/construct_returns.py
python scripts/eda.py
```

The script regenerates this report, nine PNG figures, and the EDA CSV tables. Audit reports describe the original supplied data; this report describes the corrected research version. [Research report](../REPORT.md) specifies the strategy, static comparator, timing, costs, sensitivity checks and validation.
