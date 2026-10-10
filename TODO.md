# TODO

## In Progress
Baseline TSMOM (Moskowitz-Ooi-Pedersen 2012) is complete: `scripts/run_tsmom_baseline.py` writes `reports/tsmom_baseline/`. 1985-2009: vol 11.5%, Sharpe 1.28 (paper ~1.1, no risk-free subtraction), 55 of 57 markets positive. Missing held returns (1997-03 DT/GS/LX, 2006-01 HS, 2014-12 six Eurex) are zero-filled in the script and listed in `paper_check.json`.

## Backlog
- [ ] Transaction cost model: real cost model (spread, commission, impact)
- [ ] Feedback loop
  - [ ] Baseline: report realized vs. target volatility from backtest output
  - [ ] Parameter recalibration: later
- [ ] qps data path
  - [ ] `strategy_inputs`, `run_risk_research`, `audit_daily`, `verify_legacy` still read raw CSVs directly; move them to the loaders
  - [ ] Verify the March 1997 endpoint (DT, GS, LX, SS) against the real exchange calendar
  - [ ] `data_cleaning` merges YM+ZD while the qps strategy excludes YM and EC; decide whether the TSMOM path should follow the qps treatment
- [ ] EWMA covariance is diagonal; add correlations only if a limit-bearing strategy needs them
- [ ] Split the remaining long qps modules by responsibility (`engine.py` performance functions, `research_statistics.py`, report scripts)
- [ ] Dead links in `docs/` and `reports/qps_baseline/REPORT.md`: `timing_audit/` outputs (only written when the preserved-policy run succeeds), `endpoint_sensitivity/data_validation.json`, `MIDTERM_GUIDE.md`

# Next steps
1. Defining the measure of trend:
– Can consider various different technical measures i.e. different look-
backs, crossing points (combinations of different horizons).
– Can consider various fundamental measures: will need to tailor across
markets
– Consider various events as proxies
Turning Points:
– When prices ‘turn’ i.e. go from rising to falling or vice-versa.
– Figuring out exactly how to predict turning points would be the holy
grail but these are hard to forecast, and the cost of being wrong can be
high!
