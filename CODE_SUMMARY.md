# Code summary

This project tests a monthly managed-futures trend strategy. The professor's full monthly
workbook has been assessed with four variants: rolling covariance or monthly DCC-GARCH, each
with inverse-volatility or signed within-class HRP sizing. The completed comparison retains
593 calendar months, January 1976–May 2025, and separates development through 2014 from the
2015–May 2025 test calendar. See [the monthly guide](docs/MONTHLY_FULL_SAMPLE.md) and
[results](reports/monthly_full_sample_20261116/SUMMARY.html).

The [remediation record](docs/GARCH_DATA_REMEDIATION.md) separates repaired implementation
issues from unresolved calendar, vendor and independent-validation requirements. Existing
historical reports and notebook outputs predate these fixes. The new monthly results use a
fixed 48-market universe selected from full-sample return availability. They are conditional
on that coverage choice, not independent untouched out-of-sample evidence. The current report's
verification record documents tests, accounting checks and input/source/output hashes. The
historical improvement did not persist in the 2015–May 2025 test period.

**Baseline:** size eligible markets by inverse volatility. **Enhancement:** signed hierarchical
risk parity (HRP) uses correlations to redistribute positions within each asset class while
preserving that class's forecast risk before portfolio limits. The comparison measures whether
this changes net returns, volatility, drawdown and turnover after costs; it does not assume HRP
will improve performance.

## Data-to-results pipeline

`supplied monthly returns → trend signals → monthly risk forecasts → positions → trades → results`

| Stage | Main code | Function |
| --- | --- | --- |
| Inputs | [`full_sample.py`](src/data_loader/full_sample.py): `load_full_sample_returns`; [`monthly_sample.py`](src/data_processing/monthly_sample.py): `audit_monthly_universe` | Read the professor's monthly workbook without filling returns, preserve the provided series and record the coverage-conditioned universe. |
| Signals | [`signals.py`](src/alpha_model/signals.py): `SumReturnSignal`, `BlendSignal`, `lagged` | Produce class-specific trend directions and delay them by the declared information lag. |
| Risk | [`monthly_garch.py`](src/risk_model/monthly_garch.py): `MonthlyDccGarchRiskModel`; [`rolling.py`](src/risk_model/rolling.py); [`monthly_runner.py`](src/backtest/monthly_runner.py) | Fit GARCH annually on expanding past monthly returns or use rolling covariance. Both estimators share past-only eligibility and shrinkage; each inverse-volatility shadow supplies a lagged rescale shared with its HRP arm. |
| Sizing | [`monthly_runner.py`](src/backtest/monthly_runner.py); [`InverseVolatilitySizer`](src/portfolio_construction/hold/sizing.py); [`HrpSizing`](src/portfolio_construction/hold/hrp.py) | Cross the two risk estimators with the two sizing rules, holding other controls fixed. |
| Execution | [`construct_targets`](src/portfolio_construction/targets.py), [`BandPolicy`](src/portfolio_construction/trade/policy.py), [`simulate`](src/backtest/engine.py) | Apply exposure and risk limits, trade bands and costs, then account for holdings and NAV. A missing held return stops the run. |
| Results | [`performance`](src/backtest/performance.py), [`monthly_report.py`](src/backtest/monthly_report.py) | Export all four ledgers, period metrics, equity/drawdown charts and strict all-market failures. |

## Conventions and checks

The monthly comparison uses lag 1 and a continuous account across the 2014 boundary. Portfolios
start flat in 1976 and liquidate in May 2025; insufficient common history leaves the first
36 calendar months flat. The configured trade band is 10%, ordinary cost is 2 bps per
unit of traded notional, and cash interest is zero. Prior-endpoint execution is idealized; the
daily runner's second lag is not a next-session fill. Contract-roll costs and market impact are not modeled.

The monthly runner uses the supplied monthly series directly. Tests cover timing,
future-data mutation, accounting and missing-return failures. Historical validation and its
coverage limits are documented in [OOS_VALIDATION.md](docs/OOS_VALIDATION.md); vendor vintages,
released-data coverage and executable fills still need review. Historical results are mixed:
the HRP advantage weakened under the two-month information lag.

DCC-GARCH is a research candidate, with no established independent advantage over a simpler
calibrated covariance. The completed monthly comparison does not reproduce the archived daily
GARCH specification. That separate [daily-input runner](docs/OOS_RUNNER.md) still needs compatible
daily coverage for any later assessment and stops on unresolved held endpoints. The professor's
intentional daily endpoint in 2014 does not block the completed monthly comparison.

`scripts/run_tsmom_baseline.py` is a separate paper-style development baseline. It uses fixed
raw IDs, raw RL returns and raw RL EWMA volatility, with no full-panel quality/duplicate search
or zero-filled held returns. Its fresh-output requirement preserves the archived baseline.
The daily-input HRP comparison uses the common causal RL/ER policy in both arms instead;
the monthly comparison keeps the professor's provided RL series.

## Run

Run the supplied monthly workbook with the settings in
[monthly_full_sample.json](config/monthly_full_sample.json):

```sh
PYTHONPATH=. python scripts/run_monthly_full_sample.py --output reports/my_monthly_run
```

Use a new output directory. The [monthly guide](docs/MONTHLY_FULL_SAMPLE.md) explains verification,
coverage conditions and the current results. For a separate daily-input assessment, copy
[the example declaration](config/oos_declaration.example.json),
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
