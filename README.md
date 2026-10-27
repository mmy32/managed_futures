# Managed futures research

Research on a monthly futures trend strategy, with code, conditional backtest results, and validation in the QPS baseline. Start with the [v2 research report](reports/cost_revision_20261026/REPORT_V2.md); [REPORT_V2.html](reports/cost_revision_20261026/REPORT_V2.html) embeds the charts for offline viewing.

## Strategy

The original baseline follows the sign of the preceding 12-month return sum. The default v2 keeps that signal for commodities, equities and fixed income; FX averages the 3-month and 12-month signs. A risk model uses the preceding 36 months of returns, inverse-volatility sizing, and 50% correlation shrinkage. Monthly portfolios apply a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling, a 3× gross exposure cap, and ±10% trading bands. The configured primary transaction cost is **2 bps**, with **0/1/2/5 bps** scenarios. It is an aggregate proxy charged per unit of absolute one-way traded notional divided by beginning-period NAV; turnover is not divided by two. The primary results remain trade-only. A separate [roll-cost sensitivity](reports/roll_sensitivity_20261026/SUMMARY.md) models hypothetical continuing-exposure rolls; actual contract schedules and the adjustment method remain unverified.

**Result status:** the [controlled cost comparison](reports/cost_revision_20261026/SUMMARY.md) is complete: original inputs restored and verified, historical results reproduced, and all 32 new scenarios rerun. At 2 bps, v2 TREND has 11.39% CAGR and 1.09 Sharpe in the conditional 1976–2014 study. Historical 5 bps reports remain in `reports/qps_baseline/`; notebook sections retain their original results and link to the new update. The [Step 3 band experiment](reports/band_experiment_20261026/SUMMARY.md) is complete: retain the 10% band. Narrower bands offer small historical return gains with uncertainty intervals spanning zero and worse Sharpe/drawdown. [Step 4](reports/roll_sensitivity_20261026/SUMMARY.md) is complete as a data audit and 36-case assumption-based roll sensitivity; no empirical roll model is adopted. [Step 5](reports/implementation_feasibility_20261026/SUMMARY.md) is complete as a liquidity-data audit and conditional collateral-income sensitivity. Capacity, market impact and margin/borrowing remain data-gated; [Step 6 preparation](reports/prospective_freeze_20261026/SUMMARY.md) is complete: rules and a prospective protocol are frozen. Independent validation awaits current data, activation and future observations; no paper account is running.

The strategy is compared with an always-long **STATIC** portfolio using the same eligibility rules, risk controls, and costs. Signals and risk estimates use prior observations. The 1976–2014 results are conditional on an unverified March 1997 endpoint assumption; the preserved-policy run stops on missing held returns. See [data status](docs/DATA_STATUS.md).

## File structure

| Path | Contents |
|---|---|
| `src/alpha_model/` | `Signal` interface: sum-of-returns, compounded-return and always-long signals |
| `src/risk_model/` | `RiskModel` interface: rolling covariance (qps) and EWMA daily volatility (paper); `portfolio_risk` |
| `src/portfolio_construction/` | Inverse-volatility sizing, gross and risk limits, no-trade bands, execution policy, `construct_targets` |
| `src/transaction_cost_model/` | `CostModel` interface: `LinearBpsCost`, `ZeroCost` |
| `src/backtest/` | `engine.py` (simulation, performance), `qps_baseline.py` (config to objects), `qps_v2.py` (per-asset-class trend signal), `sample_diagnostics.py` |
| `src/data_processing/` | Endpoint mapping, RL/ER source selection, March 1997 endpoint sensitivity |
| `src/data_loader/`, `src/data_cleaning/`, `src/config/` | Raw-data loaders, cleaning, and path/threshold settings |
| `config/` | QPS strategy, risk, and endpoint-assumption settings (JSON) |
| `scripts/` | `run_research.py` entry point, data construction, audits, EDA, and report builders |
| `tests/` | One folder per `src/` component; QPS timing, accounting, risk, and statistical checks |
| `docs/` | Methods, data evidence, validation notes, [code guide](docs/CODE_GUIDE.md), [data inputs](docs/DATA_INPUTS.md) |
| `reports/prospective_freeze_20261026/` | Frozen rules/source, prospective evaluation protocol, verification and pending activation requirements |
| `reports/implementation_feasibility_20261026/` | Lagged activity audit, data-readiness gates and matched 2000–2014 collateral-income sensitivity |
| `reports/roll_sensitivity_20261026/` | Contract-data audit, hypothetical roll sensitivity, event journals and cleanup inventory |
| `reports/band_experiment_20261026/` | Fixed 0/5/10% band experiment, paired uncertainty, turnover decomposition and decision |
| `reports/cost_revision_20261026/` | Current 1/2 bps reports, all 32 scenarios, validation, reference reproduction and source snapshot |
| `reports/qps_baseline/` | `REPORT.md` / `.html` and saved result tables, charts, and validation records in `output/` |

## Run the research

Python 3.11 or newer, from the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python scripts/run_research.py --validate
python scripts/run_research.py --endpoint-sensitivity
python scripts/run_research.py --variant baseline --endpoint-sensitivity  # the 12-month baseline instead of v2
```

Validation needs no source data. Research runs require the datasets described in [docs/DATA_INPUTS.md](docs/DATA_INPUTS.md). See the [code guide](docs/CODE_GUIDE.md) for the calculation sequence.
