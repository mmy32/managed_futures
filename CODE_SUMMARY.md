# Code summary

This project tests a monthly managed-futures trend strategy. The final comparison holds the
signals, risk model, limits and trading costs fixed while changing how positions are sized.
The instructor's out-of-sample data has not yet been received or assessed.

**Baseline:** size eligible markets by inverse volatility. **Enhancement:** signed hierarchical
risk parity (HRP) uses correlations to redistribute positions within each asset class while
preserving that class's forecast risk before portfolio limits. The comparison measures whether
this changes net returns, volatility, drawdown and turnover after costs; it does not assume HRP
will improve performance.

## Data-to-results pipeline

`daily closes → monthly returns → trend signals → risk forecasts → positions → trades → results`

| Stage | Main code | Function |
| --- | --- | --- |
| Inputs | [`oos_inputs.py`](src/backtest/oos_inputs.py): `load_bundle`, `strategy_inputs` | Validate declared files and build monthly and daily returns. [`endpoints`](src/data_processing/endpoints.py) uses closes available by the month-end anchor; [`select_source`](src/data_processing/strategy_inputs.py) chooses RL/ER using prior data. |
| Signals | [`signals.py`](src/alpha_model/signals.py): `SumReturnSignal`, `BlendSignal`, `lagged` | Produce class-specific trend directions and delay them by the declared information lag. |
| Risk | [`garch.py`](src/risk_model/garch.py): `DccGarchRiskModel`; [`rescaled_components`](src/backtest/qps_baseline.py) | Forecast volatility and correlations from daily returns; use a past-only baseline shadow portfolio to calibrate the shared risk model. |
| Sizing | [`comparison_components`](src/backtest/hrp_comparison.py); [`InverseVolatilitySizer`](src/portfolio_construction/hold/sizing.py); [`HrpSizing`](src/portfolio_construction/hold/hrp.py) | Build the matched baseline and enhanced cases. HRP is the only sizing change. |
| Execution | [`construct_targets`](src/portfolio_construction/targets.py), [`BandPolicy`](src/portfolio_construction/trade/policy.py), [`simulate`](src/backtest/engine.py) | Apply exposure and risk limits, trade bands and costs, then account for holdings and NAV. A missing held return stops the run. |
| Results | [`performance`](src/backtest/performance.py), [`oos_runner.py`](src/backtest/oos_runner.py) | Produce comparable metrics, paired returns, positions, ledgers and diagnostics for both portfolios and lags. |

## Conventions and checks

Lag 1 is the primary case; lag 2 is an information-delay sensitivity. Both portfolios start
flat and liquidate at the end. The configured trade band is 10%, ordinary cost is 2 bps per
unit of traded notional, and cash interest is zero. Prior-endpoint execution is idealized; the
second lag is not a next-session fill. Contract-roll costs and market impact are not modeled.

The runner constructs its inputs without the retrospective reconstruction. Tests cover timing,
future-data mutation, accounting and missing-return failures. Historical validation and its
coverage limits are documented in [OOS_VALIDATION.md](docs/OOS_VALIDATION.md); vendor vintages,
released-data coverage and executable fills still need review. Historical results are mixed:
the HRP advantage weakened under the two-month information lag.

## Run

After reviewing the released data, copy [the example declaration](config/oos_declaration.example.json),
replace its illustrative dates and provenance, and use the [input instructions](docs/OOS_RUNNER.md).
The comparison is fixed in [hrp_comparison.json](config/hrp_comparison.json), with shared
settings in [baseline_config.json](config/baseline_config.json) and
[risk_config.json](config/risk_config.json). Python 3.11+ and the project dependencies are
required. From the repository root:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
PYTHONPATH=. python scripts/run_hrp_oos.py prepare \
  --declaration path/to/declaration.json --prices-dir path/to/prices \
  --asset-map path/to/AssetMapCsv.csv --output path/to/new-preparation
PYTHONPATH=. python scripts/run_hrp_oos.py run --prepared path/to/new-preparation
```

`prepare` checks inputs and records hashes and a code snapshot without scoring. Review that
record before `run`; results are published only if all four cases complete their checks.
