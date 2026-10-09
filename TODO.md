# TODO

## In Progress
Baseline TSMOM (Moskowitz-Ooi-Pedersen 2012): 12-month sign signal, 1-month hold, 40%/vol sizing, equal-weight across markets. Monthly returns are total return, used as-is (no risk-free subtraction).
- [x] Set up environment: `.venv` (Python 3.13), `pip install -e ".[dev]"`; `pytest`, `ruff check .`, `mypy src` run clean

## Backlog
- [x] Implement `data_loader` for MonthlyReturns.csv, AssetMapCsv.csv and per-market CSVs
  - [x] `load_monthly_returns`: month-end DatetimeIndex x market IDs; fail fast on bad dates, non-numeric cells, all-NaN columns -> verified shape (552, 58); dates are last trading day of month, not always calendar month-end
  - [x] `load_asset_map`: ID-indexed; fail fast on duplicate IDs and unknown AssetClass (COMM/EQ/FI/FX) -> verified 66 rows (COMM 29, EQ 18, FI 11, FX 8)
  - [x] `load_daily_prices` from `data/raw/futures_underlying/*.csv`: Close panel; fail fast on unsorted/duplicate dates, non-positive Close -> verified 62 files; ER, ES, SC, EN have no monthly column (cleaning step); CN spans 1978-01-03 to 2014-12-31
  - [x] Paths and file names in `src/config/`
  - [x] Tests in `tests/data_loader/` with fixture CSVs
- [x] Data cleaning (`src/data_cleaning/`): combine duplicated instruments, exclude low-quality ones
  - [x] Explore data: pairwise correlations, observation counts, stale/zero shares, extreme returns; set thresholds in `src/config/`
  - [x] `find_low_quality` then `exclude` (exclude first so bad series cannot contaminate combined ones)
  - [x] `find_duplicate_groups` by correlation over overlapping months (with minimum overlap)
  - [x] `combine`: equal-weighted average per group, NaN-aware; keep group-to-members mapping
  - [x] Apply the same exclusions and groups to the daily panel and the asset map (fail fast if members disagree on asset class)
  - [x] `CleaningReport` (excluded IDs with reason, merged groups) saved to `data/processed/`
  - [x] Tests in `tests/data_cleaning/`, including idempotence
  - Result on real data: nothing excluded at thresholds (60 obs, 10% zeros, |ret| 1.0); one group merged, YM+ZD (corr 0.99997, threshold 0.99) -> ZD; panel (552, 57), asset map 65 rows. Next-highest pair CA/XU is 0.977, so not merged
- [ ] Alpha model: first forecast signal
  - [ ] `TrendSignal`: sign of trailing 12-month compounded return, using data through month-end t only
  - [ ] Signal interface `forecast(returns) -> DataFrame`; lookback in `src/config/`
  - [ ] Tests: hand-computed toy case, no look-ahead, NaN handling
- [ ] Risk model: volatility / covariance estimation
  - [ ] `ewma_volatility` per paper Eq. 1 (60-day center of mass, 261-day annualization) on daily returns -> verify against a loop implementation
  - [ ] Sample at month-ends with a documented lag so sizing uses no future data
  - [ ] Fail fast on non-positive/NaN vol where a position is requested
  - [ ] Covariance estimation: not needed for baseline, stays in backlog
- [ ] Transaction cost model
  - [ ] `CostModel` protocol and `ZeroCost` implementation (paper is gross) -> verify net == gross
  - [ ] Real cost model (spread, commission, impact): later
- [ ] Portfolio construction
  - [ ] `target_weights`: signal x 40%/vol per market, divided by number of valid markets S_t -> verify toy cases and Eq. 5 for a single market
  - [ ] `target_vol` in `src/config/`; fail fast on misaligned signal/vol indexes
- [ ] Backtest engine
  - [ ] Engine: weights set at month-end t earn month t+1 return; dependencies injected
  - [ ] Performance stats (annualized return, vol, Sharpe, max drawdown, hit rate)
  - [ ] Report 1985+ and full sample, plus by asset class
  - [ ] `scripts/run_tsmom_baseline.py`: stats table and cumulative return plot into `reports/`
  - [ ] Sanity check vs paper (1985-2009): portfolio vol ~12%, Sharpe ~1.1, nearly all markets positive
  - [ ] Tests: end-to-end toy case, look-ahead test
- [ ] Feedback loop
  - [ ] Baseline: report realized vs. target volatility from backtest output
  - [ ] Parameter recalibration: later

- [x] Incorporate `qps-baseline/` (risk-controlled 12-month trend vs STATIC): backtest/risk code in `src/backtest/` and `src/risk_model/`, audits and reports in `scripts/`, tests by component, config in `config/`, docs in `docs/`, outputs in `reports/qps_baseline/`. Moved as-is (excluded from ruff, see `pyproject.toml`)
- [x] Reconcile qps data construction with `data_loader`/`data_cleaning`
  - [x] `construct_returns` and `review_endpoints` use `load_monthly_returns` and `load_daily_prices` (`close_frames` splits the panel); raw string tokens are still read for the decimal-precision check
  - [x] Decision: the qps strategy follows Anay's treatment: YM and EC excluded, RL->ER source switch, March 1997 endpoint as a labeled sensitivity. `data_cleaning` still merges YM+ZD for the TSMOM path
  - [ ] `strategy_inputs`, `run_risk_research`, `audit_daily`, `verify_legacy` still read raw CSVs directly
  - [ ] Verify the March 1997 endpoint against the real exchange calendar
- [ ] Shared strategy abstractions up front so TSMOM baseline and qps strategy coexist
  - [ ] Interfaces for signal, risk estimate, position sizing and cost model; `engine.weights_and_signals` currently mixes signal, sizing and eligibility
  - [ ] Port qps strategy and the TSMOM baseline above behind them
- [ ] Clean up moved qps modules: pass `ruff check` and split by responsibility, then drop the `extend-exclude` list in `pyproject.toml`

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


## Done
- [x] Project scaffold
