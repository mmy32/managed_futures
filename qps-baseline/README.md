# Managed futures: risk-controlled twelve-month trend

A monthly futures strategy that goes long or short based on the sign of the preceding 12 months of returns. Positions use inverse-volatility sizing and a correlation-aware risk model estimated from the preceding 36 months. The primary settings are 50% correlation shrinkage, a 2% annual volatility floor, a 10% forecast portfolio-risk ceiling, a 3× gross exposure cap, ±10% trading bands, and 5 bps costs per traded notional.

The benchmark, **STATIC**, stays long with the same eligibility rules, risk controls, and costs. Read the [report](REPORT.md) or [offline HTML](REPORT.html) for results. The 1976–2014 study assumes March 27, 1997 is the March endpoint for DT, GS, LX, and SS; venue closures remain unverified. The preserved-policy run stops on missing held returns. See [data status](docs/DATA_STATUS.md).

## File structure

| Path | Purpose |
|---|---|
| `REPORT.md` / `REPORT.html` | Main report; HTML embeds all figures |
| [`CODE_GUIDE.md`](CODE_GUIDE.md) | Architecture and calculation sequence |
| `run_research.py` | Validation and research entry point |
| `config/` | Strategy, risk, and endpoint-assumption settings |
| `scripts/` | Data construction, backtesting, risk, statistics, audits, and reporting |
| `tests/` | Timing, accounting, risk, and statistical checks |
| `docs/` | Methods, data evidence, and validation notes |
| `output/risk/` | Preserved-policy diagnostics and validation records |
| `output/endpoint_sensitivity/` | Conditional results, charts, and assumption records |
| [`data/README.md`](data/README.md) | Required local datasets and placement instructions |
| `requirements.txt`, `pytest.ini` | Dependencies and test configuration |

## Run

Python 3.11 or newer, from this folder:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_research.py --validate
python run_research.py --endpoint-sensitivity
```

Validation needs no source data. Research runs require the inputs in [data/README.md](data/README.md). Use `--full` to rebuild source audits. A normal run returns code 2 on the preserved-policy data issue; `--endpoint-sensitivity` returns 0 when the conditional scenario completes.

[Methods](docs/RISK_METHODS.md) · [Validation](docs/VALIDATION.md)
