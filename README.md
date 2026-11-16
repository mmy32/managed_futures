# Managed futures research

The professor's full monthly workbook has been evaluated with the explicit monthly-frequency
comparison in [MONTHLY_FULL_SAMPLE.md](docs/MONTHLY_FULL_SAMPLE.md). The [completed results](reports/monthly_full_sample_20261116/SUMMARY.html)
cover four variants: rolling covariance and monthly DCC-GARCH, each with inverse-volatility and
HRP sizing, across 593 calendar months. The tables separate 1976–2014, 2015–May 2025 and the
combined period. The 48-market universe is conditional on full-sample availability; strict
all-market missing-return checks are recorded separately. The historical improvement did not
persist in the newer test period. The intentional daily-data endpoint in 2014 does
not constrain this monthly specification. Earlier verification packages retain their own
source snapshots; their source hashes identify those earlier versions.

Research on a monthly futures trend strategy. Start with the [code summary](CODE_SUMMARY.md)
and [GARCH/data remediation record](docs/GARCH_DATA_REMEDIATION.md) for the current source and
remaining data requirements. The [archived v2 research report](reports/cost_revision_20261026/REPORT_V2.md)
and [offline HTML](reports/cost_revision_20261026/REPORT_V2.html) describe earlier rolling-covariance
results; they have not been regenerated with the repaired inputs and risk model.

Read the [earlier data/daily-GARCH verification report](reports/research_verification_20261116/SUMMARY.html)
for input reconciliation, actual historical GARCH checks and synthetic regression evidence.
[Verification commands](docs/VERIFYING_RESULTS.md) let you check the saved hashes or regenerate
the package in a new directory. Those checks do not constitute a full strategy or OOS result;
the separate monthly package contains actual strategy results and its current verification record.

## Strategy

**Sizing comparison:** compare inverse-volatility sizing with signed HRP within each
asset class, holding the trend signals, risk model, limits, trading band and costs fixed. See
the [comparison definition](docs/HRP_COMPARISON.md) and [evaluation runner](docs/OOS_RUNNER.md).
That daily-input runner remains separate from the completed monthly four-variant comparison.
Monthly test results are coverage-conditioned; neither path establishes executable fills or an
independently untouched evaluation universe.

DCC-GARCH remains a configured research candidate. Its incremental historical Sharpe gain was
uncertain after roughly 40 risk-model variants on the same inspected sample; better independent
performance has not been established. The daily specification fits expanding **past** daily
history; the new monthly specification fits expanding past monthly history. The original inputs
are restored and hash-verified. A corrected full-period daily-input comparison still requires
endpoint resolution; the completed monthly comparison instead uses the supplied workbook and
the documented coverage condition. Code repairs cannot make inspected history an unseen test.

The dated result summaries below describe archived releases. Their recorded input restoration,
verification and results apply to those releases, and do not establish a corrected historical
rerun in the current checkout. Older source/configuration freezes retain their original rules;
the remediation requires a new dated snapshot before independent evaluation.

The original baseline follows the sign of the preceding 12-month return sum. The default v2
keeps that signal for commodities, equities and fixed income; FX averages the 3-month and
12-month signs. The archived reports use rolling 36-month covariance with 50% correlation
shrinkage. The separate daily-risk configuration uses rescaled DCC-GARCH with 10% shrinkage;
the completed monthly comparison uses 10% shrinkage for both estimators and shared past-only
eligibility. Its 36-month complete-return window and 60-observation annual-fit requirement
leave all four portfolios flat until January 1979, with those calendar months retained.

Monthly portfolios apply a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling,
a 3× gross exposure cap, and ±10% trading bands. The configured primary transaction cost is
**2 bps**. It is an aggregate proxy charged per unit of absolute one-way traded notional
divided by beginning-period NAV; turnover is not divided by two. The earlier daily-input
research also includes **0/1/2/5 bps** scenarios. Results remain trade-only. A separate
[roll-cost sensitivity](reports/roll_sensitivity_20261026/SUMMARY.md) models hypothetical
continuing-exposure rolls; actual contract schedules and the adjustment method remain unverified.

**Result status:** the [controlled cost comparison](reports/cost_revision_20261026/SUMMARY.md) is complete: original inputs restored and verified, historical results reproduced, and all 32 new scenarios rerun. At 2 bps, v2 TREND has 11.39% CAGR and 1.09 Sharpe in the conditional 1976–2014 study. Historical 5 bps reports remain in `reports/qps_baseline/`; notebook sections retain their original results and link to the new update. The [Step 3 band experiment](reports/band_experiment_20261026/SUMMARY.md) is complete: retain the 10% band. Narrower bands offer small historical return gains with uncertainty intervals spanning zero and worse Sharpe/drawdown. [Step 4](reports/roll_sensitivity_20261026/SUMMARY.md) is complete as a data audit and 36-case assumption-based roll sensitivity; no empirical roll model is adopted. [Step 5](reports/implementation_feasibility_20261026/SUMMARY.md) is complete as a liquidity-data audit and conditional collateral-income sensitivity. Capacity, market impact and margin/borrowing remain data-gated; [Step 6 preparation](reports/prospective_freeze_20261026/SUMMARY.md) is complete: rules and a prospective protocol are frozen. Independent validation awaits current data, activation and future observations; no paper account is running.

**Lecture 9 enhancement:** an opt-in portfolio optimizer balances tracking the trend targets against **1.5 bps per turnover**, using the current DCC strategy as comparator. The [completed evaluation](reports/pc_experiment_20261105/EVALUATION.md) finds lower turnover but no established net-return advantage; retain the existing bands. The implementation also fixes the DCC annual-refit timing at a two-month information lag. No fresh out-of-sample validation is claimed.

The archived TREND study compares the strategy with an always-long **STATIC** portfolio using
the same eligibility rules, risk controls, and costs. Signals and risk estimates use prior
observations. Those archived 1976–2014 results are conditional on an unverified March 1997
endpoint assumption; the preserved-policy daily-input run stops on missing held returns.
See [data status](docs/DATA_STATUS.md). The new monthly four-variant comparison instead uses
the workbook's supplied series and the explicit coverage condition.

## File structure

| Path | Contents |
|---|---|
| `src/alpha_model/` | `Signal` interface: sum-of-returns, compounded-return and always-long signals |
| `src/risk_model/` | `RiskModel` interface: rolling covariance, monthly/daily DCC-GARCH and EWMA daily volatility; `portfolio_risk` |
| `src/portfolio_construction/` | `hold/` inverse-volatility sizing; `scale/` gross cap and risk ceiling; `trade/` no-trade band, executed limits, execution policy; `construct_targets` |
| `src/transaction_cost_model/` | `CostModel` interface: `LinearBpsCost`, `ZeroCost` |
| `src/backtest/` | `engine.py` (simulation, performance), `qps_baseline.py` (config to objects: trend signal per asset class, risk model, rescale), `sample_diagnostics.py` |
| `src/data_processing/` | Monthly coverage audit, endpoint mapping, RL/ER source selection, March 1997 endpoint sensitivity |
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
| `reports/monthly_full_sample_20261116/` | Four monthly variants, 593-month ledgers, period tables, charts, coverage conditions and current verification record |

## Run the research

Python 3.11 or newer, from the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
PYTHONPATH=. python scripts/run_monthly_full_sample.py --output reports/my_monthly_run

# Separate historical daily-input research:
python scripts/run_research.py --validate
python scripts/run_research.py --endpoint-sensitivity
```

Validation needs no source data. Research runs require the datasets described in [docs/DATA_INPUTS.md](docs/DATA_INPUTS.md). See the [code guide](docs/CODE_GUIDE.md) for the calculation sequence.

The separate paper-style TSMOM baseline now uses fixed raw identities, causal endpoint returns
and a hard failure on missing held returns. It keeps raw RL for both monthly returns and daily
EWMA volatility; the final matched comparison uses the shared RL/ER source rule instead.
It does not reproduce the archived full-panel cleaning and zero-filled P&L. Preserve the archives:

```sh
PYTHONPATH=. python scripts/run_tsmom_baseline.py --output reports/tsmom_causal_new
```

The optional Lecture 9 experiment requires CVXPY/Clarabel and the verified reference inputs. Use a new output directory for each run:

```sh
python -m pip install -e ".[dev,pc]"
PYTHONPATH=. python scripts/run_pc_experiment.py \
  --reference reports/cost_revision_20261026 \
  --output reports/pc_experiment_new
python scripts/freeze_prospective.py verify --release reports/pc_experiment_new
```

The runner preserves production defaults, shares forecasts across policies, records solver/accounting failures, and seals its source and configuration. Its historical walk-forward results remain development evidence.
