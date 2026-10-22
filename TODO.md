# Next steps

1. Defining the measure of trend
   - Technical measures: different look-backs, crossing points (combinations of different horizons)
   - Fundamental measures: will need to tailor across markets
   - Events: consider various events as proxies
   - Turning points
     - When prices "turn", i.e. go from rising to falling or vice-versa
     - Predicting turning points exactly would be the holy grail, but they are hard to forecast and the cost of being wrong can be high

# TODO

## Baseline TSMOM

## Current strategy (qps)

Ordered by pipeline stage: data, signal, risk model, construction, costs, backtest and attribution, validation.

### Backlog

- [ ] Data
  - [ ] Verify the March 1997 endpoint (DT, GS, LX, SS) against the real exchange calendar
  - [ ] Verify vendor identities and executable futures accounting (midterm deck: all full-period results are conditional on the unverified 27 March 1997 endpoint)
- [ ] Signal: market-level predictive regressions and historical-mean forecasts (pooled significance concern); blended horizons via walk-forward selection with multiple-testing control
- [ ] Risk model: calibration std is 1.26 (TREND) and 1.41 (STATIC), so forecasts underpredict; test EWMA and fast/slow against the 36-month window, keeping shrinkage
- [ ] Portfolio construction: commodities carry most forecast risk (4.74 of 8.00 pts); test class risk budgets and contract caps, net of extra costs
- [ ] Transaction cost model: real cost model (spread, commission, impact); separate commission, spread, impact and roll trades, calibrate from liquidity data, and stress costs (midterm deck: only a flat 0/5/10 bps sensitivity so far)
- [ ] Backtest comparison and attribution
  - [ ] Compare qps with the baseline on the same footing (same sample, cost assumption and risk model): switch the qps controls on one at a time over the TSMOM setup (correlation shrinkage, limits, bands, costs). The `QPS_VS_BASELINE.md` attribution of the performance gap to the controls is inference until this is done
  - [ ] Separate direction, volatility weighting and leverage (TREND vs STATIC differ in absolute exposure, so the 5.67 pt CAGR gap is not pure signal alpha): TREND vs always-long under equal-notional and inverse-vol weights, plus fixed-gross
- [ ] Feedback loop
  - [ ] Baseline: report realized vs. target volatility from backtest output
  - [ ] Parameter recalibration: later
- [ ] Validation
  - [ ] 2005-2014 CAGR gap is only 0.14 pts (6.57% vs 6.43%); that window was inspected, so it is not a holdout
  - [ ] Freeze the rules, then evaluate on unseen post-2014 history or prospective paper trading at comparable risk and gross exposure
