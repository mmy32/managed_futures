# Code guide

The code tests one fixed 12-month trend strategy against matching always-long STATIC. One accounting engine handles both portfolios, the two trading-band settings and the three transaction-cost levels.

## Calculation sequence

`load data → compute signal → estimate risk → size positions → apply bands and limits → simulate → summarize → format report`

| Step | File / main function | What it does |
|---|---|---|
| Run | `run_research.py` | Validates, runs the pipeline and exports HTML |
| Construct | `construct_returns.py` / `assemble` | Reproduces supplied monthly returns; logs documented endpoint corrections separately |
| Select sources | `strategy_inputs.py` / `load_strategy_inputs` | Loads returns and applies the prior-only RL/ER source schedule |
| Signal and eligibility | `backtest.py` / `weights_and_signals` | Uses prior 12-month returns and complete prior risk history |
| Risk and sizing | `risk_model.py` / `build_forecasts` | Estimates lagged covariance and reduces targets to risk/exposure limits |
| Execute | `risk_model.py` / `BandPolicy` | Uses carried holdings, applies bands and enforces limits after costs |
| Account | `backtest.py` / `simulate` | Records actual trades, costs, instrument contributions and NAV; missing held returns fail |
| Summarize | `research_statistics.py` | Builds class series, rank/HAC diagnostics, risk attribution and descriptive stability blocks |
| Present | `research_report.py`, `export_report.py` | Formats results and embeds figures in offline HTML |

The exact strategy settings live in `config/baseline_config.json` and `config/risk_config.json`. The separate endpoint assumption lives in `config/endpoint_sensitivity.json`; `endpoint_sensitivity.py` changes only eight declared missing cells in an in-memory copy.

## Timing and units

For month t, direction uses returns t−12 through t−1; risk uses t−36 through t−1. Eligibility never inspects the current realized return. The source decision uses history through t−2. Exposures and costs are measured relative to beginning-month NAV. Trading costs are bps / 10,000 × actual absolute traded exposure. Net returns use zero-interest funding; funded Sharpe subtracts matching monthly RF once.

Class net contributions reconcile to monthly net return. Wealth-linked contributions reconcile to terminal P&L. Euler risk contributions add to forecast volatility; class volatilities do not add.

## Checks and reproduction

```sh
python run_research.py --validate
python run_research.py --endpoint-sensitivity
```

Tests cover past-only decisions, future mutations and prefix replay, missing-return failures, bands, after-cost limits, actual-trade cost allocation, class/NAV reconciliation, rank/HAC calendar handling and funding. The refactor reproduces 12 archived 2000–2014 runs independently of the data sensitivity.

Read [validation](docs/VALIDATION.md) for current results and [methods](docs/RISK_METHODS.md) for formulas. Tests demonstrate internal correctness under stated assumptions; they do not certify vendor history, executable fills or future returns.
