# Managed futures research

Research on a monthly futures trend strategy, with code, conditional backtest results, and validation in the QPS baseline. Start with the [research report](reports/qps_baseline/REPORT.md); [REPORT.html](reports/qps_baseline/REPORT.html) embeds the charts for offline viewing.

## Strategy

Positions go long or short based on the sign of the preceding 12 months of returns. A risk model uses the preceding 36 months of returns, inverse-volatility sizing, and 50% correlation shrinkage. Monthly portfolios apply a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling, a 3× gross exposure cap, and ±10% trading bands. The primary transaction-cost assumption is 5 bps per traded notional.

The strategy is compared with an always-long **STATIC** portfolio using the same eligibility rules, risk controls, and costs. Signals and risk estimates use prior observations. The 1976–2014 results are conditional on an unverified March 1997 endpoint assumption; the preserved-policy run stops on missing held returns. See [data status](docs/DATA_STATUS.md).

## File structure

| Path | Contents |
|---|---|
| `src/alpha_model/` | `Signal` interface: sum-of-returns, compounded-return and always-long signals |
| `src/risk_model/` | `RiskModel` interface: rolling covariance (qps) and EWMA daily volatility (paper); `portfolio_risk` |
| `src/portfolio_construction/` | Inverse-volatility sizing, gross and risk limits, no-trade bands, execution policy, `construct_targets` |
| `src/transaction_cost_model/` | `CostModel` interface: `LinearBpsCost`, `ZeroCost` |
| `src/backtest/` | `engine.py` (simulation, performance), `qps_baseline.py` (config to objects), `research_statistics.py` |
| `src/data_processing/` | Endpoint mapping, RL/ER source selection, March 1997 endpoint sensitivity |
| `src/data_loader/`, `src/data_cleaning/`, `src/config/` | Raw-data loaders, cleaning, and path/threshold settings |
| `config/` | QPS strategy, risk, and endpoint-assumption settings (JSON) |
| `scripts/` | `run_research.py` entry point, data construction, audits, EDA, and report builders |
| `tests/` | One folder per `src/` component; QPS timing, accounting, risk, and statistical checks |
| `docs/` | Methods, data evidence, validation notes, [code guide](docs/CODE_GUIDE.md), [data inputs](docs/DATA_INPUTS.md) |
| `reports/qps_baseline/` | `REPORT.md` / `.html` and saved result tables, charts, and validation records in `output/` |

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
