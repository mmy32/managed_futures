# TODO

## In Progress
Baseline TSMOM (Moskowitz-Ooi-Pedersen 2012) is complete: `scripts/run_tsmom_baseline.py` writes `reports/tsmom_baseline/`. 1985-2009: vol 11.6%, Sharpe 1.27 (paper ~1.1, no risk-free subtraction), 54 of 56 markets positive. YM and EC are excluded in `clean()` (`EXCLUDED_MARKETS`). Missing held returns (1997-03 DT/GS/LX, 2006-01 HS, 2014-12 six Eurex) are zero-filled in the script and listed in `paper_check.json`.

## Backlog
- [ ] Transaction cost model: real cost model (spread, commission, impact)
- [ ] Feedback loop
  - [ ] Baseline: report realized vs. target volatility from backtest output
  - [ ] Parameter recalibration: later
- [ ] qps data path
  - [ ] Verify the March 1997 endpoint (DT, GS, LX, SS) against the real exchange calendar
- [ ] EWMA covariance is diagonal; add correlations only if a limit-bearing strategy needs them
- [ ] Split the remaining long qps scripts by responsibility (`run_risk_research.py`, `audit_daily.py`, `eda.py`, `review_endpoints.py`)

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
