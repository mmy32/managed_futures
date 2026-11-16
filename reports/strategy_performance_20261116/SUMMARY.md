# Strategy performance: current status and archived context

**ARCHIVED CONDITIONAL RESULTS — NO CORRECTED/FULL-SAMPLE RUN**

No corrected strategy run through May 2025 has been completed. The table below contains old, conditional 1976–2014 results recalculated from archived ledgers. This report does not run a strategy or produce new out-of-sample scores.

## Available archived table

January 1976–December 2014; 468 months in every row.

| Lag | Portfolio | Net mean / yr | CAGR | Volatility / yr | Sharpe (RF=0) | Max drawdown | Turnover / yr | Cost / yr | Positive months |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 month (primary) | Inverse-vol baseline | 11.07% | 11.18% | 9.23% | 1.199 | -11.64% | 8.67× | 0.17% | 65.6% |
| 1 month (primary) | Within-class HRP | 11.19% | 11.39% | 8.47% | 1.321 | -10.13% | 13.96× | 0.28% | 65.2% |
| 2 months (sensitivity) | Inverse-vol baseline | 7.35% | 7.15% | 9.18% | 0.800 | -23.78% | 8.68× | 0.17% | 61.8% |
| 2 months (sensitivity) | Within-class HRP | 6.73% | 6.44% | 9.48% | 0.710 | -35.65% | 13.89× | 0.28% | 63.0% |

Both archived arms use class-specific trend signals, DCC-GARCH risk with a shared inverse-volatility shadow rescale, 10% trading bands, 2 bps ordinary costs and zero cash interest. The baseline sizes by inverse volatility; the enhancement uses signed HRP within each asset class. Only the sizing comparison is isolated here; this is not a test of GARCH versus rolling covariance.

These archived forecasts predate the repairs to RL/ER daily source consistency, missing daily observations, excluded-market risk estimation, optimizer failure handling and calibration timing. March 1997 returns for DT, GS, LX and SS use an unverified endpoint assumption. The archived monthly panel also accepts HS January/February 2006 returns that the current strict daily-endpoint rule leaves unknown. Recomputing statistics does not repair those forecasts or assumptions.

The full monthly workbook spans February 1969–May 2025 (676 months, 58 markets). The restored daily files end in December 2014. The 125 post-2014 monthly calendar slots cannot reconstruct the daily innovations required by this GARCH model; there are also 226 missing market-month cells in that newer period.

The actual matched-runner input preflight for January 2015–May 2025 stopped before fitting or scoring: 'Price coverage must span at least 2006-11 through 2025-05'. The saved declaration uses a January 2010 shadow start. This is a readiness check, not an attempted or completed historical backtest.

The archived primary lag-1 HRP Sharpe is higher, but turnover is higher. At lag 2 the HRP Sharpe is lower and the maximum drawdown is worse. These are inspected development results and do not establish a reliable enhancement or an independent out-of-sample advantage.

## Run readiness

| period | requested_run | status | performance_available | reason |
| --- | --- | --- | --- | --- |
| 1976-01–2025-05 | Corrected full available strategy sample | NOT_COMPLETED_BLOCKED | False | Daily prices end 2014-12; historical endpoint gaps remain unresolved. |
| 1976-01–2014-12 | Corrected historical comparison | NOT_COMPLETED | False | Current corrected strategy has not completed a full historical backtest; endpoint policy unresolved. |
| 2015-01–2025-05 | Post-development comparison | BLOCKED_NO_DAILY_EXTENSION | False | Actual input preflight rejects insufficient daily coverage; monthly returns also contain gaps. |
| 1976-01–2014-12 | Archived conditional comparison | ARCHIVED_PRE_FIX_ONLY | True | Four old ledgers independently reconciled; source/risk/data assumptions predate repairs. |

## Definitions and checks

Annual net mean = 12 × mean monthly net return; volatility = √12 × sample standard deviation. Sharpe uses zero RF and equals annual mean / annual volatility. No missing months are dropped.

CAGR compounds monthly net returns over 468 calendar months. Maximum drawdown includes the initial NAV of 1. Annual turnover and cost are 12 × their monthly arithmetic means; one-way absolute turnover is not halved.

Costs include 2 bps × turnover, including recorded entries, source transitions and terminal liquidation. Regular futures rolls, bid/ask histories and executable fills remain unverified. Positive-month rate includes all 468 months, including flat months.

All four ledgers passed the complete January 1976–December 2014 calendar, net = gross − cost, cost = turnover × 0.0002, NAV continuity and declared limit-flag checks. All independently recomputed archived metric fields match metrics.csv within absolute tolerance 1e-10. These checks verify archived arithmetic, not data provenance or current-model performance.

## Reproduce or verify

Run from the repository root. Use a new output directory.

```sh
.venv/bin/python reports/strategy_performance_20261116/build_report.py --verify-existing reports/strategy_performance_20261116

.venv/bin/python reports/strategy_performance_20261116/build_report.py --output reports/my_strategy_performance
```

See checks.csv, archived_metrics.csv, run_readiness.csv, full_sample_preflight.json and provenance.json. manifest.json records input/output hashes.
