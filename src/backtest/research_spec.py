"""Run identifiers and explicit selection of configured research results."""

import math


def run_key(band, cost, strategy, model="correlated"):
    """Preserve historical integer keys and distinguish fractional bands/rates."""
    band_text = format(band * 100, ".12g").zfill(2)
    return f"{model}_band{band_text}_{cost:g}bps_{strategy}"


def validate_research_settings(settings):
    """Reject unsupported models, invalid grids and missing primary cases early."""
    if settings["models"] != ["correlated"] or settings["primary_model"] != "correlated":
        raise ValueError("Research runner supports only the correlated model")
    for grid, primary, upper in [
        ("bands", "primary_band", 1),
        ("cost_scenarios_bps", "primary_cost_bps", math.inf),
    ]:
        values = settings[grid]
        if not values or any(not math.isfinite(x) or not 0 <= x < upper for x in values):
            raise ValueError(f"Invalid {grid}: expected finite nonnegative values below {upper}")
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate scenarios in {grid}")
        if settings[primary] not in values:
            raise ValueError(f"{primary} must be present in {grid}")
    keys = [
        run_key(b, c, "trend") for b in settings["bands"] for c in settings["cost_scenarios_bps"]
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("Scenario run identifiers collide")


def primary_key(settings, strategy):
    return run_key(
        settings["primary_band"],
        settings["primary_cost_bps"],
        strategy,
        settings["primary_model"],
    )


def select_results(frame, settings, **overrides):
    """Select one specification; never silently pick the first duplicate result."""
    filters = dict(band=settings["primary_band"], cost_bps=settings["primary_cost_bps"])
    if "model" in frame:
        filters["model"] = settings["primary_model"]
    filters.update(overrides)
    selected = frame
    for field, value in filters.items():
        selected = selected.loc[selected[field].eq(value)]
    if selected.empty:
        raise ValueError(f"Missing research results for {filters}")
    identities = [field for field in ("strategy", "hac_lags") if field in selected]
    ambiguous = selected.duplicated(identities).any() if identities else len(selected) != 1
    if ambiguous:
        raise ValueError(f"Ambiguous research results for {filters}")
    return selected.copy()
