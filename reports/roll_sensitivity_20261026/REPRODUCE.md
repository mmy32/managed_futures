# Reproducing Step 4

This release is an assumption-based monthly roll-cost sensitivity, not reconstructed contract history. The data audit and observed-data gate are recorded in `output/data_gate.json` and `output/contract_data_audit.csv`. No primary roll schedule was adopted.

Use a disposable copy of the repository with the Step 2 package and raw inputs present. Overlay `reproduction/source_snapshot.zip` for the exact source/config version and install dependencies from `pyproject.toml`. The source hashes and library versions are recorded. From that copy's root:

```sh
PYTHONPATH=. python scripts/run_roll_sensitivity.py \
  --reference reports/cost_revision_20261026 \
  --output reports/new_roll_run/output
python -m pytest -q
```

The runner refuses an existing output directory, verifies the Step 2 artifacts and 65 raw hashes, audits all daily schemas and the workbook, and records the fixed assumptions before simulation. `config/roll_sensitivity.json` defines regular 1/2 bps, complete-roll 1/2 bps, three quarterly phases and monthly rolls at the retained 10% band. Four trade-only controls plus 32 roll cases produce the 36-case comparison.

`RollSchedule` requires a boolean monthly schedule with known-at dates before each relevant holding month. These scenario calendars are deliberately fixed before the sample. They are not empirical knowledge of actual contracts. For hypothetical monthly execution, same-direction overlap is rolled at the beginning of the period, with ordinary net resizes charged separately. Source close/open trades supersede coincident assumed rolls. Fees enter `BandPolicy` and the limit solver before executed holdings and NAV are finalized.

Roll bps describe the complete close/open on matched notional. Explicit per-leg input is converted by multiplying the rate by two. The event journal splits complete-roll fees equally across matched close/open legs. Entry/exit/reversal and source-switch trades retain ordinary per-side costs. Final liquidation is an ordinary end-period exit. Economic carry and continuous-price adjustments are not fee components.

Each run exports a monthly ledger, compressed dated event journal (`*_events.csv.gz`), compressed executed exposure panel and class contribution table. Journal notional and costs reconcile to the ledger; class gross contributions less both fee components reconcile to net return. All four trade-only controls match Step 2 within absolute tolerance 1e-12 and relative tolerance 1e-10. The optional schedule is inactive by default, preserving the existing production strategy.

The final suite passes **167 tests**. Modified/new Python files pass Ruff. Full mypy still reports the pre-existing slice-index error at `src/portfolio_construction/targets.py:44`; that file was not changed. Execution and test logs are retained. `generate_report_record.py` and `package_record.py` record the presentation/packaging steps with their original machine-specific paths; numerical reproduction uses the portable command above.

Raw inputs, original Downloads files and previous result packages are retained. Scratch work and disposable caches are listed in `cleanup.json`; they are not runtime dependencies of this package. Source and artifact hashes allow integrity checks after cleanup. No commit or push was made. Step 5 has not started.
