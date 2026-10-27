# Reproducing Step 3

This is a fixed experiment on the verified conditional Step 2 return panel, not a fresh raw-data reconstruction or untouched holdout. All 65 raw hashes and all Step 2 artifact hashes were checked. The production cost remains 2 bps and the primary band remains 10%.

Use the repository with the Step 2 artifact package and raw inputs present. For exact code, overlay `reproduction/source_snapshot.zip` into a disposable copy; hashes and library versions are recorded. Install the project dependencies from `pyproject.toml`, then run from that repository root:

```sh
PYTHONPATH=. python scripts/run_band_experiment.py \
  --reference reports/cost_revision_20261026 \
  --output reports/new_band_run/output
python reports/band_experiment_20261026/reproduction/check_reversals.py \
  reports/new_band_run/output
python -m pytest -q
```

The runner refuses an existing output directory. It writes the experiment specification before forecasting or simulation. `config/band_experiment.json` contains the fixed grid, four subperiods, 20,000 draws, block lengths, seed, family size and material-gain threshold. This specification was frozen before computing the new 5% cases, but all history and the 0/10% alternatives had already been inspected.

The runner records all 12 ledgers, executed exposures, instrument costs/gross contributions, turnover components, target/risk diagnostics, paired gross/cost/net decomposition, paired bootstrap intervals and subperiods. The eight common 0/10% runs are checked against Step 2. Supplemental reversal execution checks write `reversal_execution.csv`.

Every trade belongs to one category: source close/open takes precedence, followed by entries/exits, reversals or same-direction resizes; final liquidation is separate. Reconstructed previous holdings incorporate preceding instrument returns, fees and NAV drift. Component turnover and costs reconcile to the simulator. No regular-expiry roll events are inferred from the source-switch label.

`generate_report_record.py` and `package_record.py` preserve the report-generation steps with the original machine-specific paths. They can be adapted to another experiment directory; numerical reproduction uses the portable runner above. The report's final decision is an interpretation of the frozen results, not an automatic optimizer.

`test_validation.json`, execution logs, source/input hashes and `ARTIFACT_SHA256.json` record the evidence. The full test suite passed 143 tests. Changed/new Python files pass Ruff. Repository-wide mypy still reports the pre-existing slice-index error at `src/portfolio_construction/targets.py:44`; that file was not changed.

No strategy defaults were changed, no commit or push was made, and Step 4 has not started.
