# Managed futures research

Research on a monthly futures trend strategy, with code, conditional backtest results, and validation in [`qps-baseline/`](qps-baseline/). Start with the [research report](qps-baseline/REPORT.md); [REPORT.html](qps-baseline/REPORT.html) embeds the charts for offline viewing.

## Strategy

Positions go long or short based on the sign of the preceding 12 months of returns. A risk model uses the preceding 36 months of returns, inverse-volatility sizing, and 50% correlation shrinkage. Monthly portfolios apply a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling, a 3× gross exposure cap, and ±10% trading bands. The primary transaction-cost assumption is 5 bps per traded notional.

The strategy is compared with an always-long **STATIC** portfolio using the same eligibility rules, risk controls, and costs. Signals and risk estimates use prior observations. The 1976–2014 results are conditional on an unverified March 1997 endpoint assumption; the preserved-policy run stops on missing held returns. See [data status](qps-baseline/docs/DATA_STATUS.md).

## File structure

| Path | Contents |
|---|---|
| [`qps-baseline/`](qps-baseline/) | Current research implementation and reproduction instructions |
| [`qps-baseline/REPORT.md`](qps-baseline/REPORT.md) / `.html` | Strategy, results, charts, and qualifications |
| [`qps-baseline/run_research.py`](qps-baseline/run_research.py) | Validation and research entry point |
| `qps-baseline/config/` | Strategy, risk, and endpoint-assumption settings |
| `qps-baseline/scripts/` | Return construction, backtesting, risk, statistics, audits, and reporting |
| `qps-baseline/tests/` | Timing, accounting, risk, and statistical checks |
| `qps-baseline/docs/` | Methods, data evidence, and validation notes |
| `qps-baseline/output/` | Saved result tables, charts, and validation records |
| [`qps-baseline/data/README.md`](qps-baseline/data/README.md) | Required local datasets and placement instructions |
| `src/`, `tests/`, `pyproject.toml` | Earlier framework scaffold and data-loader implementation |

## Run the research

Python 3.11 or newer, from the repository root:

```sh
cd qps-baseline
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_research.py --validate
python run_research.py --endpoint-sensitivity
```

Validation needs no source data. Research runs require the datasets described in [`data/README.md`](qps-baseline/data/README.md). See the [code guide](qps-baseline/CODE_GUIDE.md) for the calculation sequence.
