# Reproducing the cost revision

This release was built in an isolated copy of the repository, not by overwriting the historical reports. The source is the working tree based on commit `3b42f39`, including the cost-configuration changes and final reporting corrections. Nothing has been committed or pushed by this step.

## Inputs and source

1. Use a disposable copy of the repository so existing research output is preserved.
2. Overlay `reproduction/source_snapshot.zip` at that copy's root. `reproduction/source_hashes.json` records every included file. The archive includes source, tests, configs, docs and notebooks; it excludes raw data.
3. Restore `data/raw/` using the 65 files listed in `provenance.json`. Every runtime input matches the historical data hashes. The missing optional ZIP is redundant with the 62 verified daily CSVs.
4. Install the dependencies in `pyproject.toml`; exact runtime library versions are in each run's `manifest.json`.

From that disposable repository, set `PYTHONPATH=.` and run:

```sh
python scripts/construct_returns.py
python scripts/run_research.py --validate
python scripts/run_risk_research.py --variant baseline
python scripts/run_risk_research.py --variant baseline --endpoint-sensitivity
python scripts/export_report.py --report REPORT.md
python scripts/run_risk_research.py --variant v2
python scripts/run_risk_research.py --variant v2 --endpoint-sensitivity
python scripts/export_report.py --report REPORT_V2.md
```

The two preserved-policy commands are expected to exit with status 2 due to missing held returns; run the conditional commands separately afterward. The primary config runs 16 cases per variant, for 32 cases total.

## Historical reproduction

Before the new-cost grid, the execution used each variant's saved settings from `reference_reproduction/<variant>/config.json` and `base_config.json`. With those settings it reran the conditional runner, then compared the complete 12-scenario ledger set plus metrics, alpha and returns with the original saved files. The 30 comparisons use absolute tolerance 1e-12 and relative tolerance 1e-10. See `reference_reproduction/checks.json`; copied original manifests and tables, plus the reproduced 5 bps ledgers, are included. Restore the new configuration from the source snapshot before running the new grid.

The historical 2000–2014 replay is not part of this execution: its original archive configs are absent. Its earlier validation record is preserved as historical evidence, rather than represented as a fresh replay.

## Additional diagnostics and provenance

`output/cost_comparison.csv` contains all 32 cases with gross/net means, gross/net CAGR, Sharpe, drawdown, turnover, costs, exposure and calibration. Gross CAGR compounds before-fee returns along each run's actual positions; it is distinct from the separately resimulated zero-cost scenario. `output/class_cost_comparison.csv` records gross, cost and net arithmetic contributions for both versions/strategies at 1 and 2 bps. Monthly instrument/class attribution files are included.

The six existing estimator alternatives were rerun at both 1 and 2 bps without adopting a new estimator. These 24 diagnostic cases are separate from the main 32-case cost grid. Four supplemental 1 bps simulations recover full instrument attribution and are checked against the corresponding main-grid ledgers.

`reproduction/qps_step2_*.py` captures the exact execution/aggregation steps, including the recorded machine-specific staging paths. To reuse those helper scripts, update their root/staging-state paths for the disposable copy; the standard research commands above need no such edits. Execution logs and `provenance.json` retain the original locations. The final source snapshot and `ARTIFACT_SHA256.json` make the code and delivered outputs independently checkable.

All original `reports/qps_baseline/` files and all raw input bytes were checked unchanged after execution. Step 3, the 5% band experiment, has not started.
