# Code guide

The completed [monthly comparison](MONTHLY_FULL_SAMPLE.md) crosses rolling covariance or monthly
DCC-GARCH with inverse-volatility or signed within-class HRP sizing. It retains 593 calendar
months through May 2025 using a fixed 48-market universe conditioned on full-sample availability.
Shared eligibility, signals, limits, trading bands and costs make the four variants comparable.
The historical improvement did not persist in the newer test period; its universe is not an
independently untouched out-of-sample selection. The current report contains the verification
record. Earlier TREND versus STATIC studies remain development diagnostics. One accounting
engine handles all variants.
See [GARCH and data remediation](GARCH_DATA_REMEDIATION.md) before reproducing older results:
the corrected daily-risk inputs and missing-data conventions invalidate direct comparisons to
archived outputs without a matched rerun.

## Calculation sequence

`load data → compute signal → estimate risk → size positions → bound by limits → apply bands → simulate → summarize → format report`

| Step | File / main function | What it does |
|---|---|---|
| Monthly run | `run_monthly_full_sample.py` / `monthly_runner.py` | Runs the four monthly variants, exports continuous ledgers and period tables, and records strict all-market failures |
| Monthly inputs | `data_loader/full_sample.py` / `monthly_sample.py` | Reads the supplied workbook without filling blanks and audits the fixed coverage-conditioned universe |
| Historical daily-input run | `run_research.py` | Validates, runs the daily-derived research pipeline and exports HTML |
| Construct | `construct_returns.py` / `assemble` | Reproduces supplied monthly returns; logs documented endpoint corrections separately |
| Select sources | `strategy_inputs.py` / `load_strategy_inputs` | Loads returns and applies the prior-only RL/ER source schedule |
| Signal | `alpha_model/signals.py` / `Signal` | Direction in {-1, 0, +1} from returns through month t; `SumReturnSignal` (qps), `CompoundedReturnSignal` (paper), `AlwaysLongSignal` (STATIC), `SkipMonthSignal` (12-1 trend), `BlendSignal` (equal-weight average of signals), `AssetClassSignal` (routes each market to its asset class's signal), `AlwaysLongLike` (STATIC with the same eligibility as another signal) |
| Risk estimate | `risk_model/` / `RiskModel` | Lagged volatility and covariance; `RollingCovarianceRiskModel`, `MonthlyDccGarchRiskModel` (monthly returns), `DccGarchRiskModel` (daily returns), `ScaledRiskModel` (rescale), `EwmaVolatilityRiskModel` (paper, daily prices) |
| Size and bound | `portfolio_construction/` / `construct_targets` | `InverseVolatilitySizer` sizes eligible markets; `bounded_target` applies the gross cap and risk ceiling |
| Execute | `portfolio_construction/trade/policy.py` / `BandPolicy` | Uses carried holdings, applies bands and enforces limits after costs |
| Costs | `transaction_cost_model/` / `CostModel` | `LinearBpsCost` (qps) or `ZeroCost` (paper gross returns) |
| Account | `backtest/engine.py` / `simulate` | Takes targets, a cost model and an execution policy; records actual trades, costs, instrument contributions and NAV; missing held returns fail |
| Compose | `backtest/qps_baseline.py` / `configured_components` | Turns `config/*.json` into the qps objects above: the trend rule per asset class and the risk model (`rolling` or `dcc_garch`) come from `config/risk_config.json`; `rescaled_components` adds the past-only calibration rescale |
| Summarize | `backtest/sample_diagnostics.py` | Builds class series, rank/HAC diagnostics, risk attribution and descriptive stability blocks |
| Present | `monthly_report.py`, `research_report.py`, `export_report.py` | Formats results and embeds figures in offline HTML |

The monthly run's explicit settings live in `config/monthly_full_sample.json`, with shared
strategy definitions read from `config/baseline_config.json` and `config/risk_config.json`.
The daily-input research uses those shared files directly. Its separate endpoint assumption
lives in `config/endpoint_sensitivity.json`; `endpoint_sensitivity.py` changes only eight
declared missing cells in an in-memory copy. The monthly run uses the professor's supplied
series directly, including RL, and does not apply that endpoint or RL/ER daily-source override.

## Timing and units

For month t, the monthly run's 12-month signal uses returns t−12 through t−1; FX also blends
the prior three-month signal. Rolling risk uses 36 prior monthly returns. Monthly GARCH fits
expanding past monthly history at annual prior-December cutoffs, forecasts one month and
annualizes covariance by 12. Both risk estimators share prior-only eligibility requiring a
complete 36-month window and at least 60 observations at the annual fit. The minimum ten-market
rule leaves the first 36 calendar months flat; the ledgers retain them. Eligibility never
inspects the current realized return, although the fixed coverage universe uses full-sample
availability and is disclosed separately.

The daily-input runner's RL/ER source decision uses history through t−2. Exposures and costs
are measured relative to beginning-month NAV. Trading costs are bps / 10,000 × actual absolute
traded exposure. Net returns use zero-interest funding; funded Sharpe subtracts matching monthly
RF once.

Class net contributions reconcile to monthly net return. Wealth-linked contributions reconcile to terminal P&L. Euler risk contributions add to forecast volatility; class volatilities do not add.

## Checks and reproduction

For the completed monthly comparison, follow [MONTHLY_FULL_SAMPLE.md](MONTHLY_FULL_SAMPLE.md)
and use a new output directory:

```sh
PYTHONPATH=. python scripts/run_monthly_full_sample.py --output reports/my_monthly_run
```

The separate historical daily-input research commands are:

```sh
python scripts/run_research.py --validate
python scripts/run_research.py --endpoint-sensitivity
```

Tests cover past-only decisions, future mutations and prefix replay, missing-return failures, bands, after-cost limits, actual-trade cost allocation, class/NAV reconciliation, rank/HAC calendar handling and funding. The refactor reproduces 12 archived 2000–2014 runs independently of the data sensitivity.

Read [validation](VALIDATION.md) for current results and [methods](RISK_METHODS.md) for formulas. Tests demonstrate internal correctness under stated assumptions; they do not certify vendor history, executable fills or future returns.
