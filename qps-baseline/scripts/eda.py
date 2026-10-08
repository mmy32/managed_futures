"""EDA of the separately logged research return dataset. Run construction first."""
from pathlib import Path
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/qps-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/qps-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/eda"
OUT.mkdir(parents=True, exist_ok=True)
START, END, MIN_PAIRS = "2000-01", "2014-12", 60
CLASSES = ["COMM", "EQ", "FI", "FX"]
COLORS = ["#b56c27", "#2878aa", "#39845a", "#9262a7"]
plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 140})


def monthly(frame):
    frame.index = pd.to_datetime(frame.index).to_period("M")
    assert frame.index.is_unique and frame.index.is_monotonic_increasing
    assert frame.index.equals(pd.period_range(frame.index.min(), frame.index.max(), freq="M"))
    frame = frame.apply(pd.to_numeric, errors="raise")
    assert not np.isinf(frame.to_numpy()).any()
    return frame


def save(frame, name):
    frame.to_csv(OUT / f"{name}.csv", float_format="%.9g")


def stats(frame):
    return pd.DataFrame({"months": frame.count(), "mean_monthly": frame.mean(),
                         "std_monthly": frame.std(ddof=1), "mean_ann": frame.mean() * 12,
                         "vol_ann": frame.std(ddof=1) * np.sqrt(12),
                         "worst_month": frame.min(), "best_month": frame.max(),
                         "skew": frame.skew(), "excess_kurtosis": frame.kurt()})


def class_means(frame):
    return frame.T.groupby(meta.AssetClass).mean().T.reindex(columns=CLASSES)


def figure(name):
    plt.savefig(OUT / f"{name}.png", bbox_inches="tight")
    plt.close()


# Returns are decimals already: do not apply pct_change, forward-fill, or winsorize.
r = monthly(pd.read_csv(ROOT / "output/construction/monthly_returns_research.csv", index_col=0))
meta = pd.read_csv(ROOT / "data/AssetMapCsv.csv").set_index("ID")
assert meta.index.is_unique and r.columns.is_unique
assert r.columns.isin(meta.index).all() and r.notna().any().all()
bench = monthly(pd.read_excel(ROOT / "data/Lecture3_livedata.xlsx", index_col=0))
bench.columns = bench.columns.str.strip()
c = r.loc[START:END]
assert len(c) == 180 and bench.index.equals(c.index) and bench.notna().all().all()

# Separate late starts, internal gaps, and early endings instead of calling all blanks errors.
quality = meta.reindex(r.columns).copy()
quality["first"] = r.apply(lambda s: s.first_valid_index())
quality["last"] = r.apply(lambda s: s.last_valid_index())
quality["months"] = r.count()
quality["leading_missing"] = [r.index.get_loc(x) for x in quality["first"]]
quality["trailing_missing"] = [len(r) - 1 - r.index.get_loc(x) for x in quality["last"]]
quality["internal_missing"] = len(r) - quality.months - quality.leading_missing - quality.trailing_missing
quality["zero_months"] = r.eq(0).sum()
quality["longest_zero_run"] = r.apply(lambda s: s.eq(0).groupby(s.ne(0).cumsum()).sum().max())
quality["comparison_months"] = c.count()
save(quality, "coverage")
internal = r.isna() & r.notna().cummax() & r.notna().iloc[::-1].cummax().iloc[::-1]
missing = internal.stack().loc[lambda s: s].rename("missing")
missing.index.names = ["month", "ID"]
save(missing, "internal_gaps")
instrument_stats = pd.concat({"all_available": stats(r), "2000_2014": stats(c)}, names=["sample", "ID"])
save(instrument_stats.join(meta, on="ID"), "instrument_stats")

# Heuristic review flags, not evidence of errors or a normality/significance test.
mad = r.sub(r.median()).abs().median().replace(0, np.nan)
robust_z = r.sub(r.median()).div(1.4826 * mad)
flags = r.abs().gt(.30) | robust_z.abs().gt(6)
outliers = pd.concat({"return": r.where(flags).stack().dropna(), "robust_z": robust_z.where(flags).stack().dropna()}, axis=1)
outliers.index.names = ["month", "ID"]
save(outliers.join(meta, on="ID").sort_values("return"), "outliers")

# These equal-weight class averages describe the data; membership can change by month.
classes = class_means(c)
fixed = class_means(c.loc[:, c.notna().all()])  # Ex-post sensitivity only, not a tradable universe.
fixed_label = f"fixed_{int(c.notna().all().sum())}"
class_stats = pd.concat({"available": stats(classes), fixed_label: stats(fixed)}, names=["universe", "AssetClass"])
save(class_stats, "class_stats")
save(pd.concat({"available": classes, fixed_label: fixed}, axis=1), "class_returns")

# Pairwise correlations always travel with overlap counts. No covariance optimization here.
order = meta.loc[c.columns].sort_values(["AssetClass", "Name"]).index
corr = c[order].corr(min_periods=MIN_PAIRS)
overlap = c[order].notna().astype(int).T @ c[order].notna().astype(int)
save(corr, "correlation")
save(overlap, "correlation_overlap")
pairs = corr.where(np.triu(np.ones(corr.shape), 1).astype(bool)).stack().dropna().rename("correlation").to_frame()
pairs.index.names = ["ID_1", "ID_2"]
pairs["months"] = [overlap.loc[a, b] for a, b in pairs.index]
pairs["class_1"] = [meta.loc[a, "AssetClass"] for a, b in pairs.index]
pairs["class_2"] = [meta.loc[b, "AssetClass"] for a, b in pairs.index]
save(pairs.sort_values("correlation", ascending=False), "correlation_pairs")
save(classes.corr(), "class_correlation")

# Rank matched pairs AFTER dropping missing values; shift on the intact monthly calendar.
acf_rows = []
for asset in c:
    for lag in range(1, 13):
        matched = pd.concat([c[asset], c[asset].shift(lag)], axis=1).dropna()
        rho = matched.rank().corr().iloc[0, 1] if len(matched) >= MIN_PAIRS else np.nan
        pearson = matched.corr().iloc[0, 1] if len(matched) >= MIN_PAIRS else np.nan
        acf_rows.append((asset, lag, len(matched), rho, pearson, meta.loc[asset, "AssetClass"]))
acf = pd.DataFrame(acf_rows, columns=["ID", "lag", "pairs", "spearman", "pearson", "AssetClass"])
save(acf.set_index(["ID", "lag"]), "autocorrelation")

# Horizons are also aggregated, non-overlapping calendar blocks, not merely lags.
# January 2000 anchors the blocks; require all h observations in every block.
horizon_rows, horizon_values = [], []
combined = pd.concat([c, classes.add_prefix("CLASS_")], axis=1)
for horizon in [1, 3, 6, 12]:
    block = np.arange(len(combined)) // horizon
    aggregate = (1 + combined).groupby(block).prod(min_count=horizon) - 1
    aggregate.index = c.index[np.arange(horizon-1, len(c), horizon)]
    for asset in aggregate:
        series = aggregate[asset]
        pair = pd.concat([series, series.shift(1)], axis=1).dropna()
        horizon_rows.append(dict(ID=asset, horizon_months=horizon, blocks=int(series.count()),
                                 mean_per_block=series.mean(), std_per_block=series.std(ddof=1),
                                 lag_one_pairs=len(pair),
                                 lag_one_pearson=pair.corr().iloc[0, 1] if len(pair)>=8 else np.nan,
                                 lag_one_spearman=pair.rank().corr().iloc[0, 1] if len(pair)>=8 else np.nan))
        horizon_values.extend(dict(ID=asset, horizon_months=horizon, block_end=str(m), compounded_proxy_return=v)
                              for m, v in series.items())
pd.DataFrame(horizon_rows).to_csv(OUT / "horizon_statistics.csv", index=False)
pd.DataFrame(horizon_values).to_csv(OUT / "horizon_returns.csv", index=False)

# Broad-index comparisons: neither the equity universe nor the commodity weights match exactly.
benchmark_pairs = [("SP vs Mkt-RF", c.SP, bench["Mkt-RF"]),
                   ("EQ average vs Mkt-RF", classes.EQ, bench["Mkt-RF"]),
                   ("COMM average vs GSCI", classes.COMM, bench.GSCI),
                   ("SG Trend vs market total", bench["SG Trend"], bench["Mkt-RF"] + bench.RF)]
comparison = []
for label, a, b in benchmark_pairs:
    both = pd.concat([a, b], axis=1).dropna()
    comparison.append((label, len(both), both.corr().iloc[0, 1],
                       12 * (both.iloc[:, 0] - both.iloc[:, 1]).mean(),
                       np.sqrt(12) * (both.iloc[:, 0] - both.iloc[:, 1]).std()))
save(pd.DataFrame(comparison, columns=["comparison", "months", "correlation", "mean_gap_ann", "gap_vol_ann"]).set_index("comparison"), "benchmark_comparison")
save(stats(bench), "benchmark_stats")

# Four figures keep the analysis reviewable without a dashboard or notebook framework.
fig, axes = plt.subplots(2, 1, figsize=(12, 9), layout="constrained", height_ratios=[1, 2])
counts = r.notna().T.groupby(meta.AssetClass).sum().T[CLASSES]
axes[0].stackplot(r.index.to_timestamp(), counts.T, labels=CLASSES, colors=COLORS)
axes[0].set(title="Coverage expands over time", ylabel="Observed instruments", ylim=(0, 60))
axes[0].legend(ncol=4, loc="upper left")
axes[1].imshow(r[order].notna().T, aspect="auto", interpolation="nearest", cmap="Blues", vmin=0, vmax=1)
axes[1].set_yticks(range(len(order)), order, fontsize=7)
ticks = np.arange(0, len(r), 60)
axes[1].set_xticks(ticks, r.index[ticks].astype(str), rotation=30)
axes[1].set(title="Availability by instrument (white = missing)", xlabel="Month")
figure("coverage")

fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
for group, color in zip(CLASSES, COLORS):
    s = classes[group]
    axes[0, 0].scatter(s.std() * np.sqrt(12), s.mean() * 12, color=color, s=65)
    axes[0, 0].annotate(group, (s.std() * np.sqrt(12), s.mean() * 12), xytext=(6, 5), textcoords="offset points")
    for ax, values, style in [(axes[0, 1], s.cumsum(), "-"), (axes[1, 0], (1+s).cumprod()-1, "-")]:
        ax.plot(values.index.to_timestamp(), values, color=color, label=group, linestyle=style)
    growth = (1+s).cumprod()
    peak = growth.cummax().clip(lower=1)  # Include initial wealth of 1.
    axes[1, 1].plot(s.index.to_timestamp(), growth/peak-1, color=color, label=group)
axes[0, 0].set(title="Class means and volatility: 2000-2014", xlabel="Annualized volatility", ylabel="Annualized arithmetic mean")
axes[0, 0].xaxis.set_major_formatter(PercentFormatter(1))
for ax, title in zip(axes.flat[1:], ["Additive cumulative returns (lecture convention)", "Compounded return index (illustrative)", "Drawdown of compounded index"]):
    ax.set_title(title)
    ax.axhline(0, color="grey", linewidth=.6)
    ax.legend(ncol=4, fontsize=8)
for ax in axes.flat:
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(alpha=.18)
figure("class_summary")

fig, ax = plt.subplots(figsize=(12, 11), layout="constrained")
im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
ax.set_xticks(range(len(order)), order, rotation=90, fontsize=7)
ax.set_yticks(range(len(order)), order, fontsize=7)
boundaries = meta.loc[order].groupby("AssetClass", sort=True).size().cumsum().iloc[:-1] - .5
for boundary in boundaries:
    ax.axhline(boundary, color="black", linewidth=.6)
    ax.axvline(boundary, color="black", linewidth=.6)
ax.set_title("Monthly-return Pearson correlation, 2000-2014\nGrouped COMM / EQ / FI / FX; pairwise samples, minimum 60 months")
fig.colorbar(im, ax=ax, shrink=.75, label="Correlation")
figure("correlation")

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
for group, color in zip(CLASSES, COLORS):
    avg = acf.loc[acf.AssetClass.eq(group)].groupby("lag").spearman.mean()
    axes[0].plot(avg.index, avg, marker="o", markersize=3, color=color, label=group)
axes[0].set(title="Mean instrument rank autocorrelation", xlabel="Lag (months)", ylabel="Spearman correlation", xticks=range(1, 13))
axes[0].axhline(0, color="grey", linewidth=.7)
axes[0].legend(ncol=4, fontsize=8)
rolling = classes.EQ.rolling(36, min_periods=36).corr(classes.FI)
axes[1].plot(rolling.index.to_timestamp(), rolling, color="#2878aa")
axes[1].axhline(0, color="grey", linewidth=.7)
axes[1].set(title="Equity / fixed-income correlation varies", ylabel="36-month Pearson correlation", ylim=(-1, 1))
figure("dependence")

# Every contiguous observed segment is rebased separately; missing returns do
# not silently become zero and do not disappear from cumulative calculations.
path_rows = []
for page, offset in enumerate(range(0, len(order), 12), start=1):
    fig, axes = plt.subplots(4, 3, figsize=(14, 12))
    for ax, asset in zip(axes.flat, order[offset:offset+12]):
        s = c[asset]
        groups = s.isna().cumsum()
        for segment, values in s.dropna().groupby(groups):
            growth = (1 + values).cumprod()
            ax.plot(growth.index.to_timestamp("M"), growth, linewidth=1, color="#2676ab")
            additive = 1 + values.cumsum()
            ax.plot(additive.index.to_timestamp("M"), additive, linewidth=1, linestyle="--", color="#cf7a22")
            path_rows.extend(dict(ID=asset, month=str(m), segment=int(segment), wealth_index=v, additive_index=additive.loc[m])
                             for m, v in growth.items())
        ax.axhline(1, color="grey", linewidth=.5)
        ax.set_title(f"{asset}: {meta.loc[asset, 'Name']}", fontsize=9)
        ax.grid(alpha=.15)
        ax.tick_params(axis="x", labelsize=7, rotation=25)
    for ax in list(axes.flat)[len(order[offset:offset+12]):]:
        ax.set_visible(False)
    fig.suptitle("Instrument price-return indices, 2000–2014 | Blue: compounded; orange dashed: 1 + sum\nEach observed segment starts from capital 1; gaps are not bridged", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, .94))
    figure(f"instrument_cumulative_{page:02d}")
pd.DataFrame(path_rows).to_csv(OUT / "instrument_cumulative_segments.csv", index=False)

print(f"Saved EDA to {OUT}. {r.shape[1]} instruments, {len(r)} months, {r.notna().sum().sum()} observations.")
print(class_stats.round(4).to_string())
print(f"Internal gaps: {quality.internal_missing.sum()}; outlier review flags: {len(outliers)}.")
print("EDA complete; run run_research.py for strategy evaluation.")

# Regenerate the narrative alongside the tables so data corrections cannot leave it stale.
class_rows = []
for cls, row in stats(classes).iterrows():
    class_rows.append(f"| {cls} | {row.mean_monthly:.3%} | {row.std_monthly:.3%} | {row.mean_ann:.2%} | {row.vol_ann:.2%} |")
within = pairs.loc[pairs.class_1.eq(pairs.class_2), 'correlation'].mean()
acfone = acf[acf.lag.eq(1)].groupby('AssetClass').spearman.mean()
figure_links = '\n'.join(f'- [Instrument plots, page {i}](output/eda/instrument_cumulative_{i:02d}.png)' for i in range(1,6))
report = f'''# Historical 2000–2014 EDA — separate from the current presentation

This is the retained historical EDA, with its original 2000–2014 sample and available-instrument methodology. It is not the new prior-eligible 1976–2014 class analysis. This report uses the separately logged research return dataset. Strategy results and remaining implementation limitations are in [current report](RESEARCH_REPORT.md).

## Data and audit status

There are {len(r)} months (January 1969–December 2014), {r.shape[1]} instruments, and {int(r.count().sum()):,} observed returns. The original CSV's 20,987 returns and 11,029 blanks were reproduced at stored precision. Eight returns were added only to the research version after exchange-calendar verification; original raw files remain unchanged. [Construction changes](output/construction/return_changes.csv) and [endpoint review](ENDPOINT_REVIEW.md) document every exception.

The raw audit examined 62 files and 457,155 daily rows. It found 458 extreme-move flags, 219 repeated-close runs (at least four observations), seven repeated-OHLC runs, and one OHLC inconsistency. These are review flags, not proven price errors. All 127 previously flagged monthly extremes trace to the raw monthly closes. See [daily audit](DAILY_PRICE_AUDIT.md) and [unresolved issues](output/construction/unresolved_issues.csv).

The research data retains {int(quality.internal_missing.sum())} internal monthly gaps: SS has 18; DT, GS and LX have two each. The verified HS January/February 2006 gaps and six December 2014 early endings are resolved in this version. No missing return is filled with zero; no outlier is winsorized. EC retains its supplied FX label for descriptive EDA, while the strategy excludes it pending identity verification. YM and ZD remain in EDA so their near-duplicate exposure is visible; the strategy retains ZD only.

![Coverage](output/eda/coverage.png)

## Monthly mean and standard deviation

The main comparison sample is 180 months, January 2000–December 2014. [Instrument statistics](output/eda/instrument_stats.csv) include explicit monthly mean/std and all-history statistics. Class returns below average available instruments within each month; membership changes. They are descriptive averages, not the volatility-scaled strategy.

| Class | Monthly mean | Monthly std | Annual mean | Annual vol |
|---|---:|---:|---:|---:|
{chr(10).join(class_rows)}

Annual mean = 12 × monthly mean; annual vol = sqrt(12) × sample monthly std. Annualization does not correct for autocorrelation. The {int(c.notna().all().sum())}-instrument complete-sample sensitivity in [class statistics](output/eda/class_stats.csv) is selected ex post and must not define a tradable universe. Different all-history samples should not be used for unqualified instrument rankings.

## Cumulative returns

The class chart includes additive cumulative returns (the lecture convention), compounded indices and compounded drawdowns. Instrument plots provide both 1 + cumulative sum and cumulative product of 1 + returns. Each contiguous observed segment is rebased independently; missing months are not bridged. Compounding is an illustrative price-return index until the vendor's futures P&L denominator is verified.

![Class return summaries](output/eda/class_summary.png)

{figure_links}

[Instrument cumulative values](output/eda/instrument_cumulative_segments.csv) preserve segment identifiers.

## Correlations

The Pearson matrix uses at least {MIN_PAIRS} overlapping observations per pair, with [overlap counts](output/eda/correlation_overlap.csv). Average signed within-class pairwise correlation is {within:.3f}; across-class correlation is {pairs.loc[pairs.class_1.ne(pairs.class_2),'correlation'].mean():.3f}. YM/ZD correlation is {c.YM.corr(c.ZD):.6f}. Pairwise deletion can produce a non-positive-semidefinite matrix; this exploratory matrix is not used for portfolio optimization.

![Correlations](output/eda/correlation.png)

## Autocorrelation and horizons

Lecture pp. 25–26 discuss rank autocorrelation of monthly returns. The primary [autocorrelation table](output/eda/autocorrelation.csv) therefore compares monthly returns at calendar lags 1–12, with both Pearson and Spearman estimates and matched-pair counts. The intact calendar is shifted before missing pairs are dropped; ranks are computed on the matched sample. Mean lag-one Spearman correlations by class are {', '.join(f'{k}: {v:.3f}' for k,v in acfone.items())}.

To also address aggregated horizons, [horizon statistics](output/eda/horizon_statistics.csv) and [block returns](output/eda/horizon_returns.csv) report 1-, 3-, 6-, and 12-month non-overlapping compounded returns, anchored at January 2000. A block requires every underlying monthly observation. These include block mean/std and lag-one correlations between blocks. Annual blocks provide only 15 observations, so estimates are especially uncertain. Monthly lag tables require at least 60 matched pairs; block autocorrelations require at least eight. No pooled t-statistics or significance claims are made across the many dependent comparisons.

![Dependence](output/eda/dependence.png)

## Benchmarks and limitations

The supplied workbook matches all 180 comparison months. SG Trend has annualized mean {bench['SG Trend'].mean()*12:.2%} and volatility {bench['SG Trend'].std()*np.sqrt(12):.2%}, consistent with lecture p9. [Benchmark comparisons](output/eda/benchmark_comparison.csv) are descriptive return gaps and correlations, not regression alpha. The current strategy report implements HAC alpha but withholds the extended-period estimate while missing held returns block evaluation. No bond series is supplied for a literal 60/40 benchmark.

Lecture p14 confirms that daily prices are already rolled. The exact roll adjustment, currency conversion, collateral convention and executable contract accounting remain unspecified. Raw prices, volume and open interest are available; actual roll dates and execution cost history are not. Retaining source values is not certification of their economic accuracy.

## Reproduce

```sh
python scripts/construct_returns.py
python scripts/eda.py
```

The script regenerates this report, nine PNG figures, and the EDA CSV tables. Audit reports describe the original supplied data; this report describes the corrected research version. [Research report](RESEARCH_REPORT.md) specifies the strategy, static comparator, timing, costs, sensitivity checks and validation.
'''
(ROOT/'docs').mkdir(exist_ok=True)
report = report.replace('(output/', '(../output/').replace('(RESEARCH_REPORT.md)', '(../REPORT.md)')
(ROOT/'docs/EDA.md').write_text(report)
