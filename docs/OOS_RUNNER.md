# Matched HRP evaluation runner

The runner compares the fixed inverse-volatility baseline with signed HRP within each asset
class. Both use the same class-specific trend signals, baseline-derived DCC-GARCH rescale,
limits, band, ordinary trading costs and calendar. Lag 1 is primary and lag 2 is an
information-delay sensitivity. Both portfolios start flat at the evaluation boundary and
liquidate at its end. These are idealized prior-endpoint fills, not executable fill estimates.

## Input contract

The course upload's format is not yet known. Before using it, normalize the historical warmup
and released data into a consistent, continuous dataset:

```text
normalized/
├── AssetMapCsv.csv          # ID, AssetClass; existing Name/Ccy columns may be present
└── prices/
    ├── AN.csv               # date index, Close column, one file per declared market
    ├── ...
    └── ER.csv               # required if RL is in the strategy universe
```

Daily file indices must use `YYYY-MM-DD`, be ordered, unique and timezone-naive, and each file
must have exactly one `Close` column. Close values must be positive and finite; prices with zero
or negative values cannot use this percentage-return model. The
declaration describes the actual timezone, source, vintage, continuous-contract adjustment,
price definition and availability convention. Use `unknown` when a fact is unavailable; it is
not a certification that the data were point-in-time or executable. Keep the chosen universe
fixed independently of future performance. Historical and evaluation prices must use compatible
units and adjustment conventions. The runner does not invent a way to splice two vintages.

The runner constructs month-end prices from closes known at the anchor, subject to a three-day
freshness limit. It rebuilds RL/ER source choice from prior data; it does not load the
retrospective source schedule. When ER is selected for RL, the risk model uses ER's own daily
returns for that month, without taking a price ratio across the two series. This normalized
input convention can differ from archived research; a matched historical rerun is required before
directly comparing those historical figures with the new evaluation. The
[historical validation](OOS_VALIDATION.md) documents a wider replay blocked by an HS endpoint
gap and a restricted replay after that gap; neither is independent out-of-sample evidence.

The price files must reach at least 38 months before the declared shadow start under the current
36-month risk window and two-month maximum lag. The shadow must begin at least 36 months before
evaluation under the current settings. The run also requires enough valid, nonflat shadow returns
to initialize the configured rescale and enough eligible markets at evaluation start. These
calendar checks are necessary but do not certify data continuity or quality for each market. The
risk model retains earlier observations for fitting but only requests portfolio forecasts from
the declared shadow start; it does not fit unused periods when the early universe may be too small.

## Two-stage workflow

1. Copy `config/oos_declaration.example.json` to a new file and replace all placeholders. The
   dates are illustrative, not approved evaluation dates. The example universe lists the 58
   markets from the archived development panel; the base configuration excludes EC and YM from
   holdings, although they may still enter risk-model estimation. Review and fix the universe,
   evaluation dates, shadow start, provenance and conventions before viewing performance. The
   evaluation must start after the 2014 development sample.
2. From the project root, prepare a new directory. This validates the declaration and basic
   coverage, hashes the inputs, code and configuration, saves a source/configuration snapshot,
   and records settings **without scoring**.

```sh
PYTHONPATH=. python scripts/run_hrp_oos.py prepare \
  --declaration path/to/declaration.json \
  --prices-dir path/to/normalized/prices \
  --asset-map path/to/normalized/AssetMapCsv.csv \
  --output path/to/new-preparation
```

3. After the preparation record and data have been reviewed, run the unchanged prepared case:

```sh
PYTHONPATH=. python scripts/run_hrp_oos.py run --prepared path/to/new-preparation
```

The runner rejects changed inputs or code, insufficient warmup, missing held returns, accounting
failures and limit breaches. It writes a failed status if execution stops, and publishes results
only when all four cases pass. A failed or completed assessment is not overwritten; make a new
preparation record after correcting a problem. `assessment/results/` contains a concise summary,
metrics, paired monthly returns, ledgers, targets, exposures, diagnostics and output hashes.

The local preparation timestamp and hashes provide an audit trail, not independent proof that a
declaration preceded all access to the data or that the vendor supplied historical vintages.
Do not select parameters, dates or the preferred lag from the evaluation results. The released
data still need the planned step-5 review before performance claims are made.
