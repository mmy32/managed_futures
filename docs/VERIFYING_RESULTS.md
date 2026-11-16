# Reading and reproducing the verification results

For the new monthly strategy backtest, use [MONTHLY_FULL_SAMPLE.md](MONTHLY_FULL_SAMPLE.md)
and [the monthly results](../reports/monthly_full_sample_20261116/SUMMARY.html). That package
records the updated implementation, actual portfolio results and 408 passing tests. The earlier
data/daily-GARCH package discussed below retains its original source snapshot. Its source hashes
will correctly report a mismatch against the newer monthly implementation; that does not mean
its saved data or historical outputs have been changed. Use the monthly runner's
`--verify-existing` command to verify the current monthly results.

Start with [the readable verification report](../reports/research_verification_20261116/SUMMARY.html)
or its [Markdown version](../reports/research_verification_20261116/SUMMARY.md). The report separates
code correctness, input-file identity and readiness to evaluate the real strategy. Green code
checks do not establish a GARCH performance advantage or supply the missing post-2014 daily data.
The original 1969–2014 daily files have now been restored and verified. Earlier report directories
ending in `_monthly_only` preserve the interim audit before that restoration; the linked report
is the current verification package.

## What to read

| Artifact | What it establishes | What it does not establish |
| --- | --- | --- |
| `SUMMARY.html` / `SUMMARY.md` | A readable account of the checks, supplied data and remaining blockers. | A real-data strategy result unless the report explicitly records a completed declared assessment. |
| `input_audit/*.csv` | File identities, monthly coverage, missing cells and historical overlap. | Vendor correctness, exchange-session calendars or independently untouched evaluation data. |
| `historical_data_checks/` | Reconciliation of the restored daily endpoints with published monthly arithmetic and explicit records of known gaps. | Proof that a historical venue was open or that a vendor's adjustments produced executable returns. |
| `historical_garch/` | Actual annual GARCH/DCC fits and covariance diagnostics using restored historical daily observations. | A completed full-period strategy backtest, net performance or an independent improvement. |
| `garch_checks/*.csv` | Synthetic numerical checks, including comparisons with independently specified expected behavior. | Historical net returns, realistic fills or superiority over another risk model. |
| `checks/test_results.xml` and logs | The commands run and their actual pass/failure results against that source. | Evidence that absent real prices were reconstructed or that unverified conventions are valid. |
| `manifest.json` | The recorded inputs and verification provenance. | Independent public timestamping or a vendor's point-in-time data guarantee. |

Read the failed or blocked checks as well as the successful ones. A missing held return must stop
a strategy assessment; it must not become zero profit, a deleted month or a favorable restart.
The [remediation record](GARCH_DATA_REMEDIATION.md) explains the code changes and which remaining
questions require data rather than another code change. Older reports and notebook results
retain their original assumptions and metrics.

## What the supplied files contain

The November 16 audit confirms all **65 original input files** against the SHA-256 hashes recorded
in the earlier research release: the asset map, historical monthly CSV, benchmark workbook and
62 daily instrument files. The new full-sample workbook is recorded separately:

| Canonical local input | Coverage or contents |
| --- | --- |
| `data/raw/AssetMapCsv.csv` | 66 instrument IDs and their supplied metadata. |
| `data/raw/MonthlyReturns.csv` | 552 monthly rows, January 1969–December 2014, with 58 return columns; January 1969 is entirely blank. |
| `data/raw/Lecture3_livedata.xlsx` | 180 monthly rows, January 2000–December 2014, with SG Trend, GSCI, factor returns and RF. |
| `data/raw/futures_underlying/*.csv` | 62 original daily files; 457,155 observations collectively spanning January 2, 1969–December 31, 2014. Includes separate RL and ER sources. |
| `data/raw/MonthlyReturns_FullSample.xlsx` | 676 ordered, unique, consecutive months, February 1969–May 2025, with the same 58 return columns. |

Returns are stored in decimal units. For example, January 2000 RF is `0.0041`, meaning **0.41%**;
do not divide these numbers by 100 again. The full-sample workbook's observed historical values
agree within the declared CSV-rounding and Excel-representation allowance: the maximum absolute
difference is approximately `4.66e-8` in decimal-return units. Across 551 common months, all
20,987 jointly observed cells pass the per-cell tolerance (half the original token's last decimal
unit plus `1e-12` decimal units; exact zeros use `1e-12`). Long CSV tokens differ from Excel by
up to roughly `1e-15`, so this is not a claim of literal token equality. No observed historical
cell is dropped. The workbook adds
exactly six historical values: AX, DT, UB, UZ, XU and XX in December 2014.

The workbook does **not** resolve the four instruments' March/April 1997 blanks or HS's
January/February 2006 blanks. A supplied monthly return cannot establish its actual daily
endpoint or certify the relevant exchange calendar.

There are 125 new months, January 2015–May 2025. Their missing cells need review before any
assessment:

| Series | Missing months in that interval | Observed pattern |
| --- | ---: | --- |
| AP | 33 | June 2022–February 2025 are blank; March–May 2025 resume with approximately +22.71%, +42.96% and +44.34%. |
| HS | 2 | January and February 2017 are blank. |
| EC | 25 | Last supplied observation is April 2023; the strategy already excludes EC because its identity/classification is unresolved. |
| SS | 42 | Last supplied observation is November 2021. |
| XX | 4 | Last supplied observation is January 2025. |
| ZD | 120 | Last supplied observation is May 2015. |

These are data-review flags, not permission to interpolate, rescale or replace a market. In
particular, AP's gap and resumed values require the vendor's interval/identity/adjustment
explanation; their magnitude alone does not identify the cause. ZD ending while YM continues
does not authorize a newly chosen replacement rule after inspecting evaluation outcomes.

## Run the verification yourself

From the repository root, with the project environment and supplied files present:

```sh
.venv/bin/python scripts/verify_research.py --verify-existing reports/research_verification_20261116
.venv/bin/python scripts/verify_research.py --output reports/my_verification
```

The first command checks the existing report's output, supplied-input and source/configuration
hashes without rerunning model fits. It fails if those recorded bytes have changed. This is a
local integrity check, not independently timestamped proof. The second command reruns the work.

Use a new output directory each time. The command gathers the input audit, daily/monthly
reconciliation, actual historical GARCH diagnostics, synthetic numerical checks and recorded
verification commands into a new readable report. It does not score the
post-2014 strategy or overwrite the archived research packages. Read its final status and logs;
a recorded blocker is part of the result.

To run the individual checks:

```sh
.venv/bin/python -m pytest -q
.venv/bin/mypy src
PYTHONPATH=. .venv/bin/python scripts/verify_garch_fixes.py --output reports/my_garch_checks
PYTHONPATH=. .venv/bin/python scripts/verify_original_inputs.py --output reports/my_historical_data_checks
PYTHONPATH=. .venv/bin/python scripts/verify_historical_garch.py --output reports/my_historical_garch
```

`pytest` exercises the regression suite, including information timing, missing-data behavior,
excluded estimation inputs, optimizer failures and account reconciliation. `mypy` checks source
types. `verify_garch_fixes.py` writes numerical evidence from synthetic histories to a new
directory. `verify_original_inputs.py` checks actual restored daily/monthly arithmetic and
known endpoint gaps. `verify_historical_garch.py` fits the actual historical model and exports
fit/covariance diagnostics, rather than strategy returns. The real-data tools and main runner
default to `data/raw/`; use their optional `--raw-dir path/to/raw` for another input location.
Use the report's XML/log records for the actual test count and outcomes of that run.

## What is still required for real strategy results

The restored daily files allow real historical fitting, endpoint reconciliation and source
diagnostics. They end in December 2014. A completed full-period strategy comparison still needs
the held-return endpoint gaps resolved under a declared policy; fitting a historical covariance
matrix does not itself complete that strategy backtest. The expected original input layout is
in [DATA_INPUTS.md](DATA_INPUTS.md).

For the new period, compatible 2015–May 2025 daily source prices remain absent. Provide that
extension, enough historical warmup, vendor/source definitions, adjustment and currency conventions,
availability timestamps
and relevant session calendars where available. The [matched runner](OOS_RUNNER.md) requires a
declared universe, calendar, execution policy and frozen comparison before scoring. Monthly
coverage after 2014 makes the workbook a potential evaluation input, not independent proof that
it was never inspected or used in earlier choices. Record prior access and development history
before describing any future assessment as untouched out of sample.

Until those requirements are met, verification establishes implementation behavior, the supplied
files' contents and the model's behavior on actual historical daily data. It does not establish
full strategy performance, resolve the old endpoint assumptions or prove that GARCH/HRP improves
on the matched baseline.
