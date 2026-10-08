# Managed futures: risk-controlled twelve-month trend

This project tests whether following one-year trends adds value over an always-long portfolio with the same risk controls.

**Read first:** [midterm report](REPORT.md) or [offline HTML](REPORT.html). At 5 bps trading costs, the conditional 1976–2014 study reports **10.82% CAGR, 1.06 Sharpe and −15.82% maximum drawdown**, versus STATIC's **5.15%, 0.48 and −55.95%**. The recent-period advantage is smaller.

**Data qualification:** these results assume March 27, 1997 is the March endpoint for DT, GS, LX and SS. The exact venue closures remain unverified. The preserved-policy run stops on missing held returns; [data-status note](docs/DATA_STATUS.md) explains the issue. January 1976 is flat because only seven instruments meet the ten-instrument minimum.

## Files to review and share

| File | Purpose |
|---|---|
| `REPORT.md` / `.html` | Main presentation report: eight sections, timing table, charts and results |
| `ENDPOINT_SENSITIVITY.md` / `.html` | Compatible copy of the conditional presentation report |
| `MIDTERM_GUIDE.md` | 15-minute presentation flow, strength assessment and likely questions |
| `CODE_GUIDE.md` | Short explanation of architecture and main functions |
| `run_research.py`, `config/`, `scripts/`, `tests/` | Reproducible code and frozen settings |
| `docs/` | Supporting methods, validation and data evidence |
| Selected files in `output/` | Charts, result tables and validation records |

Keep `.gitignore`, `requirements.txt`, `pytest.ini` and `data/README.md` too. The sharing rules exclude course datasets, local environments, caches and bulky run archives. Markdown needs its chart folders; HTML embeds all figures. Historical EDA and earlier audits are supporting material, not the current presentation.

## Run

Python 3.11 or newer:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_research.py --validate
python run_research.py --endpoint-sensitivity
```

Tests need no course data. For the analysis, place inputs as described in [data/README.md](data/README.md). Add `--full` to rebuild all source audits. A normal run returns code 2 on the preserved-policy data issue; the sensitivity command returns 0 when the conditional scenario completes.

The strategy uses prior 12-month signals, prior 36-month risk estimates, 50% correlation shrinkage, a 2% volatility floor, a 10% forecast-risk ceiling, a 3× gross cap and ±10% trading bands. Main cost: 5 bps. [Methods](docs/RISK_METHODS.md) · [Validation](docs/VALIDATION.md).
