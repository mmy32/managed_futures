# Running the strategy on the professor's monthly data

The professor's daily file ending in 2014 and monthly workbook ending in May 2025 are intentional
sample boundaries. The monthly backtest uses `data/raw/MonthlyReturns_FullSample.xlsx` directly,
with the supplied asset map. It does not require outside daily prices. Raw inputs remain unchanged.

The four fixed comparisons combine rolling monthly covariance or monthly DCC-GARCH risk with
inverse-volatility or signed within-class HRP sizing. Monthly GARCH is estimated from monthly
returns and forecasts one month ahead, with covariance annualized by 12. It is a new frequency
specification; daily parameters and 21-day aggregation do not carry over. All variants use the
same past-only eligibility rules and other portfolio controls.

## Calendar and readable outputs

Historical monthly observations before 1976 initialize the model. A single continuous portfolio
runs January 1976–May 2025: 593 monthly observations. The report separates the original development
calendar, January 1976–December 2014, from January 2015–May 2025, and includes the combined period.
There is no portfolio restart or liquidation at the 2014 boundary. Subperiod statistics summarize
the matching slices of each continuous ledger. Sequential model updates use only prior returns.

`SUMMARY.html` opens offline and contains the performance tables, equity and drawdown figure,
strict all-market results, omissions and interpretation. `SUMMARY.md` provides a text version.
`metrics.csv` retains unrounded values; `metrics_display.csv` uses readable percentages.
`model_parameters.csv`, `universe_audit.csv`, `checks.csv` and `status.json` retain supporting evidence.

The completed [November 16 monthly run](../reports/monthly_full_sample_20261116/SUMMARY.html)
includes 408 passing tests and independent reconstruction of all four portfolio accounts and
all 12 performance-table rows. See its `validation/` directory for the XML test record, lint/type
logs and independent-statistics checks. Source, input and output hashes are recorded in its
manifest. The common history requirements leave the first 36 calendar months flat; all four
portfolios first invest in January 1979. Those months remain in the reported 1976-start statistics.

The tables include annual arithmetic net mean, CAGR, annual volatility, zero-rate Sharpe,
maximum drawdown, annual turnover, annual cost and the share of positive months. Sharpe does
not subtract the lecture workbook's RF from these zero-interest futures proxy returns. Costs
are the configured 2 bps per unit of absolute one-way traded notional, with entry and final
liquidation charged. Executable fills, ordinary futures expiry rolls and market impact are
not established by the supplied monthly-return data.

The unrounded CSV also retains `cost_cash_per_initial_capital`. In every period this field uses
the continuous account's original 1976 capital as its denominator; it is not rebased to January
2015. The readable tables use annual mean cost instead.

The supplied workbook and asset map stay local under `data/raw/`; report exports do not copy
the course-return panel. Saved-package verification requires those original inputs in the
documented locations. Their manifest paths are relative to the repository, so the same files
can be verified from another checkout location.

## Blank observations and scope of the results

The user requested both a strict all-market attempt and a full-calendar conditional table.
The strict attempt keeps the predeclared strategy exclusions and stops if an existing holding
has an unknown realized return. Missing returns do not become zero, and portfolio months are
not silently deleted.

The conditional table fixes the markets with uninterrupted supplied returns from their first
observation through May 2025. Leading pre-inception blanks are allowed and past-history
requirements control entry. Coverage, rather than return magnitudes, determines this fixed
market set. EC and YM retain their previously declared exclusions. The coverage audit records
every omitted market and its missing history.

This rule uses availability from the entire workbook and can create survivorship or availability
selection bias. Consequently, January 2015–May 2025 is a chronological test calendar, **not an
independently untouched out-of-sample universe**. The report labels the comparison as conditional
on full-sample coverage. The table can describe how the monthly specifications behaved on those
supplied returns; it cannot establish an independent performance advantage by itself.

## Commands

Run from the repository root with the project environment and the professor's files present.
Use a new output directory; existing reports are preserved.

```sh
PYTHONPATH=. .venv/bin/python scripts/run_monthly_full_sample.py --output reports/my_monthly_run

PYTHONPATH=. .venv/bin/python scripts/run_monthly_full_sample.py --verify-existing reports/monthly_full_sample_20261116
```

The first command fits the monthly models, runs the portfolio comparisons and writes a new
report package. The second checks the saved package's hashes and exported accounting evidence.
Hash agreement establishes local integrity of recorded files; it does not authenticate the
professor's vendor conventions or independently timestamp an experiment.
