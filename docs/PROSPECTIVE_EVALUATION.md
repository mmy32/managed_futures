# Frozen prospective evaluation protocol

This is the Step 6 preparation record. **The rules are frozen; independent performance validation is still pending.** The available 65 raw files end in December 2014, and the 1976–2014 results have already informed research choices. The team elected prospective preparation because no untouched dataset was supplied. Repartitioning the old sample cannot make it independent.

## Candidate and comparisons

The primary candidate is v2 TREND: 12-month return-sum direction for commodities, equities and fixed income; equal average of 3- and 12-month directions for FX. Opposing FX signs cancel. Keep the trailing 36-month covariance, 50% correlation shrinkage, 2% annual volatility floor, inverse-volatility scale 0.4, minimum ten eligible instruments, exclusions, prior-only source selection, 10% forecast-risk ceiling, 3× gross cap and 10% relative band. The exact rules live in the sealed source/config snapshot.

Run six portfolios on the same calendar: v2 TREND, matching v2 STATIC and original baseline TREND, each at ordinary costs of 1 and 2 bps. The original baseline uses the 12-month signal in every class. The primary cost remains 2 bps per absolute one-way traded notional / beginning NAV. Do not halve turnover. Include entries, drift-adjusted resizes, source close/open trades and final liquidation. Resimulate each cost case, because costs affect NAV, drift and band decisions.

The primary comparison is v2 TREND minus its matching STATIC at 2 bps. The secondary comparison is v2 TREND minus baseline TREND at 2 bps. These assess the specified portfolios, not pure directional skill: independently constrained portfolios can have different exposures. No equal-risk or alternative-sizing claim follows from them. The 1 bps cases are fixed sensitivity checks, not a selection menu.

The primary evaluation uses zero cash interest and no assumed regular roll schedule. The Step 4 roll and Step 5 collateral cases remain separate research sensitivities. These are trade-only price-return proxies; they are not verified all-in implementation returns. Do not add fitted impact, borrowing or margin estimates without the missing evidence.

## Activation gate

There is no active paper account, live feed, scheduled job or recorded prospective return. Before activation:

1. Supply licensed, current data with dated provenance, contract/source definitions, units, time zones, publication times and a consistent return construction. Record any vendor backfills or revisions. Confirm the universe and exclusions before inspecting evaluation outcomes.
2. Supply at least 36 contiguous monthly warmup observations before the first holding month, with sufficient history for the existing two-month-lag source-selection rule. A recent contiguous history is required; do not bridge the 2014-to-present gap with missing or fabricated returns. Enforce the existing eligibility rules even if the portfolio is flat.
3. Reconcile the new data adapter with the frozen construction, endpoint and source conventions before activation. The unresolved March 1997 overlay is historical context, not permission to fill a new missing endpoint. Missing held returns stop reporting; no forward fill, asset deletion or retrospective exception.
4. Record an activation document containing this release's manifest hash, the actual first holding month, data/input hashes and availability timestamps, source schedule and known-at dates, initial NAV 1 and flat positions, execution convention, and the exact 36-month calendar. The first month must follow the freeze and data-readiness work. All declarations must precede observation of evaluation-month returns.
5. Verify the sealed code and settings. Runtime copies of `base.start` and `base.end` may be set to the predeclared evaluation dates; all other strategy parameters remain sealed. Record those two administrative overrides. Any data adapter or execution change requiring code changes needs a new dated freeze before outcomes are examined.

The current simulator assumes idealized execution at the prior monthly endpoint. Target calculations must be archived after the required prior observations are available and before the next return period begins. If that deadline cannot be met, do not backdate the order: activation is not ready under this convention. Recording a proxy at that endpoint does not demonstrate an obtainable fill. Executable paper trading requires a separately declared arrival/fill convention and contract-level data; that is not implemented or started here.

## Monthly record and failure handling

Before each holding month, archive the input snapshot and availability times, source choices/known-at dates, eligibility, signals, target weights, covariance, proposed and band-adjusted exposures, prior drifted positions, expected ordinary costs and after-fee limits. Record an actual timestamp and hashes. A hash detects later changes relative to the retained record; a local timestamp alone is not independent proof of preregistration.

After the month, append the observed returns and provenance, realized gross return, ordinary fees, separately identified cash/roll components (zero under this primary specification), net return, NAV, turnover, exposures, forecast risk and any failure. Keep data revisions as new versions with reasons; preserve the originally observed result and label any corrected replay. Never silently overwrite or drop an inconvenient month.

Carry state continuously from flat initialization. Do not restart or liquidate at interim checkpoints. Liquidate at the predeclared final endpoint, charge its costs, and present mark-to-market and liquidation effects separately. Source switches use the frozen policy, not whichever series later looks better.

Require gross plus cash income minus all booked fees to equal net return; instrument costs must sum to portfolio fees and compounded returns to NAV. Check gross and forecast-risk limits after entry fees at each decision. These ceilings are not promises about realized volatility or intramonth exposure. A data/accounting failure pauses publication, retains its calendar slot and blocks a complete performance claim until resolved. It does not authorize a fresh sample start or performance-based horizon extension.

## Evaluation and decision

The first 36 consecutive calendar months are the fixed operational evaluation horizon. Months 12 and 24 receive descriptive monitoring only; do not retune, declare success or stop based on interim performance. Thirty-six months is a practical monitoring horizon, not a statistical power calculation or evidence that all market regimes have been covered.

At the final endpoint report, for all six portfolios: gross and net annual mean, CAGR, annual volatility, clearly labeled zero-rate mean/volatility ratio, drawdown, worst month, ordinary cost drag, turnover, average/max gross exposure, forecast versus realized risk, class contributions, eligibility and failure counts. Do not label the zero-cash ratio as an excess Sharpe against an unprovided current RF series. Display monthly NAV, drawdown, exposure and risk-calibration histories together.

The primary endpoint is the annualized mean of monthly paired net-return differences versus STATIC at 2 bps; the secondary endpoint is the corresponding difference versus baseline TREND. Use the frozen seed and 20,000 paired circular block resamples, six-month blocks and a mandatory twelve-month-block sensitivity. Show nominal 95% and Bonferroni family-adjusted intervals for the two endpoints. Thirty-six observations provide limited information about serial dependence and tails; intervals are descriptive and do not correct the entire prior strategy search. Report both endpoints and block lengths regardless of sign; do not choose the favorable interval.

Complete accounting and timing checks are a prerequisite for interpreting any performance. A positive mean with intervals spanning zero is inconclusive. Even a positive lower interval is only encouraging evidence for this proxy and horizon, not a capacity, deployment or universal outperformance claim. Consider drawdowns, costs, calibration and exposure alongside the mean. There is no automatic promotion rule. Any subsequent strategy revision becomes a new research version and needs a new prospective record; the existing record remains unchanged.

## Current handoff

The machine-readable declaration is `config/prospective_evaluation.json`. The Step 6 release contains source/config snapshots, raw-input hashes, references to earlier result manifests, environment versions and a verification command. Fresh data, a verified adapter, an activation record and future outcomes remain outstanding. No prospective performance table is populated with historical results.
