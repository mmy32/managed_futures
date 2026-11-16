"""Read-only reconciliation and coverage of supplied monthly return panels."""

from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd


def stored_tolerance(token: str) -> float:
    """Half a stored decimal unit plus 1e-12 for Excel/float representation noise."""
    try:
        value = Decimal(str(token))
    except InvalidOperation as error:
        raise ValueError(f"Invalid stored return token: {token!r}") from error
    if not value.is_finite():
        raise ValueError("Observed return tokens must be finite")
    if value == 0:
        return 1e-12
    return 0.5 * 10.0 ** int(value.as_tuple().exponent) + 1e-12


def reconcile_monthly(original, expanded, tokens):
    """Compare shared cells at original precision; additions never become repairs implicitly."""
    if not original.columns.equals(expanded.columns):
        raise ValueError("Monthly panels must have identical market IDs and order")
    if not tokens.index.equals(original.index) or not tokens.columns.equals(original.columns):
        raise ValueError("Stored tokens must align with the original monthly panel")
    months = original.index.intersection(expanded.index)
    records, observed, maximum = [], 0, 0.0
    for month in months:
        for market in original:
            before, after = original.loc[month, market], expanded.loc[month, market]
            if pd.isna(before) and pd.isna(after):
                continue
            kind, difference, tolerance = "added", np.nan, np.nan
            if pd.notna(before) and pd.isna(after):
                kind = "removed"
            elif pd.notna(before) and pd.notna(after):
                observed += 1
                difference = abs(float(after) - float(before))
                maximum = max(maximum, difference)
                tolerance = stored_tolerance(tokens.loc[month, market])
                if difference <= tolerance:
                    continue
                kind = "changed_beyond_stored_precision"
            records.append({"month": str(month), "market": market, "change": kind,
                            "original": before, "full_sample": after,
                            "absolute_difference": difference, "tolerance": tolerance})
    changes = pd.DataFrame(records, columns=["month", "market", "change", "original",
                                             "full_sample", "absolute_difference", "tolerance"])
    summary = {
        "shared_months": len(months), "joint_observed_cells": observed,
        "max_observed_absolute_difference": maximum,
        "observed_changes_beyond_precision": int(changes.change.eq(
            "changed_beyond_stored_precision").sum()),
        "added_observations": int(changes.change.eq("added").sum()),
        "removed_observations": int(changes.change.eq("removed").sum()),
        "original_only_months": [str(m) for m in original.index.difference(expanded.index)],
        "original_only_observed_cells": int(original.loc[
            original.index.difference(expanded.index)].notna().sum().sum()),
        "full_sample_only_months": [str(m) for m in expanded.index.difference(original.index)],
        "tolerance_rule": "Half the original CSV token's last decimal unit plus 1e-12 "
                          "decimal units for Excel/float representation; exact zeros use 1e-12.",
    }
    return summary, changes


def market_coverage(returns, meta, development_end):
    """Distinguish pre-inception/trailing blanks from gaps between observed returns."""
    post = returns.loc[development_end + 1:]
    records = []
    for market in returns:
        series = returns[market]
        first, last = series.first_valid_index(), series.last_valid_index()
        interior = int(series.loc[first:last].isna().sum()) if first is not None else 0
        records.append({
            "market": market, "asset_class": meta.loc[market, "AssetClass"],
            "first_observed_month": str(first) if first is not None else "",
            "last_observed_month": str(last) if last is not None else "",
            "observed_months": int(series.notna().sum()),
            "missing_months": int(series.isna().sum()), "interior_missing_months": interior,
            "post_development_months": len(post),
            "post_development_observed": int(post[market].notna().sum()),
            "post_development_missing": int(post[market].isna().sum()),
        })
    return pd.DataFrame(records)


def missing_runs(returns, start):
    """List gaps and the first observed return after each; never replace either."""
    panel = returns.loc[start:]
    records = []
    for market in panel:
        pending = []
        for month, value in panel[market].items():
            if pd.isna(value):
                pending.append(month)
            elif pending:
                records.append(_run(market, pending, month, value))
                pending = []
        if pending:
            records.append(_run(market, pending, None, np.nan))
    return pd.DataFrame(records, columns=["market", "gap_start", "gap_end", "missing_months",
                                         "resumption_month", "resumption_return_decimal"])


def _run(market, months, resumed, value):
    return {"market": market, "gap_start": str(months[0]), "gap_end": str(months[-1]),
            "missing_months": len(months), "resumption_month": str(resumed) if resumed else "",
            "resumption_return_decimal": value}
