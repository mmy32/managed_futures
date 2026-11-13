"""Build a matched inverse-volatility versus HRP comparison.

The existing rescale is estimated once from the inverse-volatility shadow portfolio.
Both cases use that same risk model; only the hold-stage adjustment differs.
"""

import json
from dataclasses import replace
from pathlib import Path

from src.backtest.qps_baseline import (
    configured_components,
    hold_adjustment,
    rescaled_components,
)
from src.config import PROJECT_ROOT
from src.risk_model import ScaledRiskModel

EXPECTED_PORTFOLIOS = {
    "baseline": {"hold_sizing": "inverse_vol"},
    "enhanced": {"hold_sizing": "hrp_within_class"},
}


def validate_comparison(spec):
    """Reject changes that would make the comparison differ beyond the hold stage."""
    expected_fields = {"base_config", "risk_config", "strategy", "rescale_shadow", "portfolios"}
    if set(spec) != expected_fields:
        raise ValueError("Comparison must contain exactly the declared shared settings and portfolios")
    if spec["strategy"] != "trend" or spec["rescale_shadow"] != "baseline":
        raise ValueError("Comparison requires trend portfolios and the baseline rescale shadow")
    if spec["portfolios"] != EXPECTED_PORTFOLIOS:
        raise ValueError("Comparison requires inverse-vol baseline and within-class HRP enhancement")


def load_comparison(root: Path = PROJECT_ROOT):
    """Load the named comparison and its common base/risk settings."""
    spec = json.loads((root / "config/hrp_comparison.json").read_text())
    validate_comparison(spec)
    base = json.loads((root / spec["base_config"]).read_text())
    risk = json.loads((root / spec["risk_config"]).read_text())
    if risk["base_config"] != spec["base_config"]:
        raise ValueError("Comparison and risk settings must use the same base configuration")
    return spec, base, risk


def comparison_components(spec, base, risk, returns, meta, source, known, daily=None):
    """Return shared settings and two component sets; no returns are scored here.

    The baseline override is explicit even if the shared base defaults to HRP. The
    rescale shadow and both variants use the same baseline base settings. Timing and
    missing-data handling must be verified before using this for evaluation.
    """
    validate_comparison(spec)
    shared_base = {**base, **spec["portfolios"]["baseline"]}
    baseline = configured_components(shared_base, risk, meta, daily=daily)
    baseline = rescaled_components(baseline, returns, meta, shared_base, risk, source, known)
    if risk.get("risk_model", {}).get("rescale") is not None and not isinstance(
        baseline.risk_model, ScaledRiskModel
    ):
        raise ValueError("Comparison cannot proceed without its configured risk rescale")
    enhanced = replace(
        baseline,
        adjustment=hold_adjustment(spec["portfolios"]["enhanced"]["hold_sizing"]),
    )
    return shared_base, {"baseline": baseline, "enhanced": enhanced}
