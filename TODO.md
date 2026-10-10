# TODO

## In Progress
Baseline TSMOM (Moskowitz-Ooi-Pedersen 2012): 12-month sign signal, 1-month hold, 40%/vol sizing, equal-weight across markets. Monthly returns are total return, used as-is (no risk-free subtraction). The signal, EWMA risk model, zero-cost model, sizer and engine exist and are tested; what remains is running and checking the strategy.
- [ ] Paper parameters in `src/config/` (12-month lookback, 40% instrument scale, 1-month lag) instead of constructor arguments at the call site
- [ ] `scripts/run_tsmom_baseline.py`: compose `CompoundedReturnSignal` + `EwmaVolatilityRiskModel` + `InverseVolatilitySizer` + no limits + `ZeroCost` via `construct_targets` and `simulate`; write stats table and cumulative return plot into `reports/`
- [ ] Performance stats: add hit rate; report 1985+ and full sample, plus by asset class
- [ ] Sanity check vs paper (1985-2009): portfolio vol ~12%, Sharpe ~1.1, nearly all markets positive
- [ ] Single-market check of the sizing against paper Eq. 5

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
