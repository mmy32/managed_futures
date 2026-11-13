# Managed futures research

Research on a monthly futures trend strategy, with code, conditional backtest results, and validation in the QPS baseline. Start with the [v2 research report](reports/cost_revision_20261026/REPORT_V2.md); [REPORT_V2.html](reports/cost_revision_20261026/REPORT_V2.html) embeds the charts for offline viewing.

## Strategy

**Planned final comparison:** compare inverse-volatility sizing with signed HRP within each
asset class, holding the trend signals, risk model, limits, trading band and costs fixed. See
the [comparison definition](docs/HRP_COMPARISON.md) and [evaluation runner](docs/OOS_RUNNER.md).
The runner is prepared for normalized inputs; the released data and execution assumptions still
need validation before any out-of-sample assessment.

The original baseline follows the sign of the preceding 12-month return sum. The default v2 keeps that signal for commodities, equities and fixed income; FX averages the 3-month and 12-month signs. The archived reports use rolling 36-month covariance with 50% correlation shrinkage; the current configuration uses rescaled DCC-GARCH with 10% shrinkage. The shared base currently defaults to HRP sizing; the planned comparison explicitly selects inverse-volatility sizing for its baseline. Both use a 36-month eligibility history. Monthly portfolios apply a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling, a 3× gross exposure cap, and ±10% trading bands. The configured primary transaction cost is **2 bps**, with **0/1/2/5 bps** scenarios. It is an aggregate proxy charged per unit of absolute one-way traded notional divided by beginning-period NAV; turnover is not divided by two. The primary results remain trade-only. A separate [roll-cost sensitivity](reports/roll_sensitivity_20261026/SUMMARY.md) models hypothetical continuing-exposure rolls; actual contract schedules and the adjustment method remain unverified.

**Result status:** the [controlled cost comparison](reports/cost_revision_20261026/SUMMARY.md) is complete: original inputs restored and verified, historical results reproduced, and all 32 new scenarios rerun. At 2 bps, v2 TREND has 11.39% CAGR and 1.09 Sharpe in the conditional 1976–2014 study. Historical 5 bps reports remain in `reports/qps_baseline/`; notebook sections retain their original results and link to the new update. The [Step 3 band experiment](reports/band_experiment_20261026/SUMMARY.md) is complete: retain the 10% band. Narrower bands offer small historical return gains with uncertainty intervals spanning zero and worse Sharpe/drawdown. [Step 4](reports/roll_sensitivity_20261026/SUMMARY.md) is complete as a data audit and 36-case assumption-based roll sensitivity; no empirical roll model is adopted. [Step 5](reports/implementation_feasibility_20261026/SUMMARY.md) is complete as a liquidity-data audit and conditional collateral-income sensitivity. Capacity, market impact and margin/borrowing remain data-gated; [Step 6 preparation](reports/prospective_freeze_20261026/SUMMARY.md) is complete: rules and a prospective protocol are frozen. Independent validation awaits current data, activation and future observations; no paper account is running.

**Lecture 9 enhancement:** an opt-in portfolio optimizer balances tracking the trend targets against **1.5 bps per turnover**, using the current DCC strategy as comparator. The [completed evaluation](reports/pc_experiment_20261105/EVALUATION.md) finds lower turnover but no established net-return advantage; retain the existing bands. The implementation also fixes the DCC annual-refit timing at a two-month information lag. No fresh out-of-sample validation is claimed.

The strategy is compared with an always-long **STATIC** portfolio using the same eligibility rules, risk controls, and costs. Signals and risk estimates use prior observations. The 1976–2014 results are conditional on an unverified March 1997 endpoint assumption; the preserved-policy run stops on missing held returns. See [data status](docs/DATA_STATUS.md).

## File structure

| Path | Contents |
|---|---|
| `src/alpha_model/` | `Signal` interface: sum-of-returns, compounded-return and always-long signals |
| `src/risk_model/` | `RiskModel` interface: rolling covariance (qps) and EWMA daily volatility (paper); `portfolio_risk` |
| `src/portfolio_construction/` | `hold/` inverse-volatility sizing; `scale/` gross cap and risk ceiling; `trade/` no-trade band, executed limits, execution policy; `construct_targets` |
| `src/transaction_cost_model/` | `CostModel` interface: `LinearBpsCost`, `ZeroCost` |
| `src/backtest/` | `engine.py` (simulation, performance), `qps_baseline.py` (config to objects: trend signal per asset class, risk model, rescale), `sample_diagnostics.py` |
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
| `reports/qps_baseline/` | Markdown reports and saved result tables, charts, and validation records in `output/` |

## Run the research

Python 3.11 or newer, from the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python scripts/run_research.py --validate
python scripts/run_research.py --endpoint-sensitivity
```

Validation needs no source data. Research runs require the datasets described in [docs/DATA_INPUTS.md](docs/DATA_INPUTS.md). See the [code guide](docs/CODE_GUIDE.md) for the calculation sequence.

The optional Lecture 9 experiment requires CVXPY/Clarabel and the verified reference inputs. Use a new output directory for each run:

```sh
python -m pip install -e ".[dev,pc]"
PYTHONPATH=. python scripts/run_pc_experiment.py \
  --reference reports/cost_revision_20261026 \
  --output reports/pc_experiment_new
python scripts/freeze_prospective.py verify --release reports/pc_experiment_new
```

The runner preserves production defaults, shares forecasts across policies, records solver/accounting failures, and seals its source and configuration. Its historical walk-forward results remain development evidence.
