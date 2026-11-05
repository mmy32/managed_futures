# Reproduce Step 5

From the repository root, with project dependencies installed:

```sh
PYTHONPATH=. python scripts/run_implementation_feasibility.py --reference reports/cost_revision_20261026 --roll-reference reports/roll_sensitivity_20261026 --output /tmp/implementation_feasibility_new/output
python -m pytest -q
```

Use a new output directory. The runner verifies the Step 2 and Step 4 manifests plus all 65 raw input hashes. Raw inputs are not redistributed in this package. `reproduction/source_snapshot.zip` includes current source, scripts, tests, configs and methods; SHA-256 records the exact snapshot inputs. The numerical runner writes data tables; `SUMMARY.md`/HTML provide the reviewed interpretation. The workbook RF is used only for January 2000–December 2014, without filling or extension. Production settings are unchanged.
