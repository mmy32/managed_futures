# Step 6: prospective rules frozen, validation pending

**The preparation is complete. Independent performance validation is not.** The team selected a prospective protocol because no untouched dataset was supplied. All 65 available raw files end by December 2014; the historical results have already informed strategy decisions. No paper account, live feed or scheduled monitoring has been started.

## Frozen decisions

| Item | Declaration |
|---|---|
| Candidate | v2 TREND: 12-month directions outside FX; equal 3/12-month sign blend in FX |
| Comparators | Matching v2 STATIC and original 12-month baseline TREND |
| Runs | Each portfolio at 1 and 2 bps; six cases total, with 2 bps primary |
| Risk and execution | Existing 36-month covariance, 50% correlation shrinkage, 2% volatility floor, 10% forecast-risk ceiling, 3× gross cap, 10% band and prior-only eligibility/source rules |
| Cost scope | Ordinary one-way traded-notional proxy; zero cash interest; no assumed regular-roll schedule |
| Initialization | NAV 1, flat positions, current contiguous warmup history; retain all calendar months |
| Horizon | First 36 months after a documented activation; descriptive checkpoints at 12 and 24 months |
| Primary endpoint | Paired annualized mean net return: v2 TREND minus v2 STATIC at 2 bps |
| Secondary endpoint | Paired annualized mean net return: v2 TREND minus original baseline TREND at 2 bps |
| Uncertainty | Fixed 20,000-draw paired block bootstrap; 6-month blocks and mandatory 12-month sensitivity; nominal and two-comparison family-adjusted intervals |
| Decision discipline | No performance-based early stopping, retuning, sample restart or automatic promotion |

The 36-month horizon is an operational choice, not a power calculation. Uncertainty intervals are descriptive. Portfolio differences do not isolate directional skill because exposures can differ. Evaluate returns alongside costs, drawdowns, exposure and risk calibration. Trade-only proxy results would not establish executable capacity or all-in returns.

## What is still needed

1. Current, dated data and enough contiguous warmup history to apply the frozen risk, signal and source rules. Do not bridge the gap from 2014 with invented observations.
2. A verified data adapter and source/endpoint conventions, declared before evaluation outcomes are examined. Any necessary code change requires a new version of the freeze.
3. A timestamped activation record specifying the first holding month, the exact 36-month calendar, input availability, initial state and this release's hash. Only evaluation start/end dates may be administratively overridden in runtime config copies.
4. Before-month target/input records, then append-only monthly outcomes and failure logs. Missing held returns or failed reconciliation block a complete performance claim; they do not justify dropping months.

The simulator assumes an idealized prior-endpoint fill. Targets must be recorded before the next return period begins; missed deadlines cannot be backdated. Executable paper trading would need contract-level data and a separately declared fill convention. No prospective performance has been generated here.

## Frozen package and verification

The release seals **115 source/config/protocol files** and records **65 raw-input hashes**, the four prior release manifests, the current Git HEAD plus uncommitted source state, and numerical-package versions. It includes the exact source archive. Local hashes detect subsequent changes relative to the retained record; they do not constitute independent public timestamping.

From the repository root:

```sh
python scripts/freeze_prospective.py verify --release reports/prospective_freeze_20261026
```

Verification checks archive contents, current source/config membership and hashes, raw inputs and every artifact listed in the prior releases. Changed rules or added source files fail verification. Never overwrite this release; an intentional change requires a new version and an explanation of its effect on prospective status.

The detailed [evaluation protocol](../../docs/PROSPECTIVE_EVALUATION.md) and [machine-readable declaration](../../config/prospective_evaluation.json) define recording, failure handling, metrics and decision rules. The archive preserves both. **All 179 tests pass**, including six freeze-integrity tests. Changed Python files pass Ruff. Repository-wide lint retains 12 existing active-code/notebook findings and 98 in archived reproduction scripts; mypy retains the existing `targets.py:44` error. Test and lint outcomes are recorded in `validation.json` and `execution_logs/`.

**Handoff:** preparation complete; activation and future observations remain outstanding. The final evaluation criterion in Delivery F is still pending.
