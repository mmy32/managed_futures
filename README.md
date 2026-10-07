# managed_futures

A systematic managed futures research framework: forecast returns across ~60 futures markets, size risk, account for trading costs, construct a portfolio, backtest it, and feed realized results back into the models.

## Quickstart

```bash
# 1. Clone
git clone <repo-url> && cd managed_futures

# 2. Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env

# 4. Run tests
pytest
```

## Usage

```python
from src.data_loader import load_data

data = load_data("data/raw/MonthlyReturns.csv")
```

## Architecture

The strategy is a pipeline of six model components plus shared infrastructure. Each component lives in its own package under `src/` and talks to the others through narrow interfaces.

```
 data/raw ──► data_loader ──► data_processing ──► feature_registry / transformations
                                                          │
                                                          ▼
                                                    alpha_model ──────► expected returns (forecasts)
                                                          │
                          risk_model ◄── returns ─────────┤──────► covariance, vol, risk limits
                                                          │
                     transaction_cost_model ◄─────────────┤──────► expected cost of trading
                                                          ▼
                                              portfolio_construction ──► target weights
                                                          │
                                                          ▼
                                                      backtest ──► P&L, turnover, performance stats
                                                          │
                                                          ▼
                                                    feedback_loop ──► recalibrate models
                                                          │
                                         (updated parameters flow back to alpha / risk / cost models)
```

| Component | Package | Responsibility |
|---|---|---|
| Alpha model | `src/alpha_model/` | Forecasts: turns features (e.g. trend, carry) into expected returns per market. |
| Risk model | `src/risk_model/` | Risk measurement and control: volatility and covariance estimation, risk budgets, exposure and drawdown limits. |
| Transaction cost model | `src/transaction_cost_model/` | Estimates commissions, spread, slippage and market impact for a proposed trade. |
| Portfolio construction | `src/portfolio_construction/` | Combines forecasts, risk and costs into target positions (optimization, sizing, constraints). |
| Backtest | `src/backtest/` | Simulates the strategy historically; computes returns, turnover and performance statistics. |
| Feedback loop | `src/feedback_loop/` | Compares realized vs. forecast outcomes (returns, risk, costs) and recalibrates model parameters. |

Supporting packages: `config/` (settings), `models/` (data schemas), `data_loader/` (ingestion), `data_processing/` (cleaning), `feature_registry/` (feature definitions), `transformations/` (reusable transforms), `utils/` (helpers).

## Data

All datasets live in `data/` (gitignored — large files).

| Path | Contents |
|---|---|
| `data/raw/MonthlyReturns.csv` | Monthly returns by date (rows) and futures market ID (columns), from 1969. |
| `data/raw/AssetMapCsv.csv` | Market ID → name, currency, asset class. |
| `data/raw/futures_underlying/` | One CSV per market (62 files) of underlying futures data. |
| `data/raw/FuturesUnderlyingData.zip` | Original archive of `futures_underlying/`. |
| `data/raw/Lecture3_livedata.xlsx` | Live data workbook from Lecture 3. |
| `data/interim/` | Intermediate cleaning outputs. |
| `data/processed/` | Analysis-ready datasets. |

`data/raw/` is immutable — never modify it.

## Project Structure

```
managed_futures/
├── README.md
├── TODO.md
├── CLAUDE.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── data/
│   ├── raw/                     # immutable source data
│   │   └── futures_underlying/
│   ├── interim/
│   └── processed/
├── src/
│   ├── config/
│   ├── models/
│   ├── data_loader/
│   ├── data_processing/
│   ├── feature_registry/
│   ├── transformations/
│   ├── alpha_model/
│   ├── risk_model/
│   ├── transaction_cost_model/
│   ├── portfolio_construction/
│   ├── backtest/
│   ├── feedback_loop/
│   └── utils/
├── tests/                       # mirrors src/
├── scripts/
├── notebooks/
├── research/
└── reports/
```
