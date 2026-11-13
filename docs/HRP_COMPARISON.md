# Matched HRP comparison

The primary research comparison uses the existing trend strategy in both cases:

| Case | Hold sizing |
| --- | --- |
| Baseline | Inverse volatility |
| Enhanced | Signed HRP within each asset class |

`config/hrp_comparison.json` names both cases. The common settings are read from
`config/baseline_config.json` and `config/risk_config.json`: the same class-specific signals,
DCC-GARCH risk model, information lag, limits, 10% trading band and 2-bps ordinary-trade cost.
The baseline's inverse-volatility sizing is explicit even though the shared base file currently
defaults to HRP for other research. Existing historical experiments keep their original settings.

`src/backtest/hrp_comparison.py` constructs one unscaled inverse-volatility shadow portfolio,
estimates the risk rescale from it once, and gives the same rescaled risk model to both cases.
Only the enhanced case receives the HRP hold adjustment. Keeping the shadow common prevents
each variant from acquiring a different risk forecast solely because its sizing differs.

The prior hold notebook used the then-configured HRP shadow for its comparisons. Its saved
results are historical evidence for that setup, not results from this newly specified
inverse-volatility-shadow comparison; do not relabel them as such without a matched rerun.

This comparison has a [two-stage evaluation runner](OOS_RUNNER.md), but no actual out-of-sample
evaluation or independently verified freeze. The
endpoint and rescale failure paths were corrected and both portfolios passed synthetic
full-path timing checks; see [the timing audit](HRP_TIMING_AUDIT.md) for remaining data and
execution limitations. The historical information-lag sensitivity there shows that the HRP
advantage reverses when information is delayed an extra month. Test dates, warmup, starting
holdings and the normalized data provenance must be declared before the evaluation.
