"""Describe the professor's monthly universe without filling or changing returns.

Complete coverage after inception is an explicit, retrospective sample condition.
It uses availability through the declared sample end and therefore cannot certify
an ex-ante tradable universe or an untouched out-of-sample evaluation.
"""

from collections.abc import Collection, Mapping

import numpy as np
import pandas as pd

from src.risk_model.base import check_monthly_calendar

COVERAGE_SELECTION_NOTE = (
    "Universe selected using return availability through the full sample end; "
    "leading pre-inception blanks are allowed. This is a retrospective coverage "
    "condition with possible survivorship bias, not an ex-ante universe."
)


def _validated_sample(returns, excluded, sample_end):
    if returns.empty or not returns.columns.is_unique:
        raise ValueError("Monthly universe requires nonempty returns and unique market IDs")
    check_monthly_calendar(returns)
    if np.isinf(returns.to_numpy(dtype=float)).any():
        raise ValueError("Monthly universe returns must be finite or explicitly missing")
    end = pd.Period(sample_end, freq="M")
    if end < returns.index[0] or end > returns.index[-1]:
        raise ValueError("Declared sample end must lie within the supplied monthly calendar")
    if set(excluded) - set(returns.columns):
        raise ValueError("Declared exclusions contain markets absent from monthly returns")
    sample = returns.loc[:end]
    empty = sample.columns[sample.isna().all()].tolist()
    if empty:
        raise ValueError(f"Markets have no observed return by the sample end: {empty}")
    return sample


def _market_audit(name, values, excluded, development_end):
    first, last = values.first_valid_index(), values.last_valid_index()
    after_first = values.loc[first:]
    missing = int(after_first.isna().sum())
    predeclared = name in excluded
    if predeclared:
        detail = excluded[name] if isinstance(excluded, Mapping) else "Declared exclusion"
        reason = f"Predeclared strategy exclusion: {detail}"
    elif missing:
        reason = "Incomplete coverage after inception through the declared sample end"
    else:
        reason = ""
    return {
        "market": name,
        "first_observed": str(first),
        "last_observed": str(last),
        "missing_internal": int(values.loc[first:last].isna().sum()),
        "missing_after_first": missing,
        "missing_post_2014": int(after_first.loc[development_end + 1:].isna().sum()),
        "included_coverage": not predeclared and missing == 0,
        "exclusion_reason": reason,
    }


def audit_monthly_universe(
    returns: pd.DataFrame,
    excluded: Mapping[str, str] | Collection[str],
    sample_end: str | pd.Period,
    *,
    development_end: str | pd.Period = "2014-12",
) -> pd.DataFrame:
    """Audit all markets and mark a fixed, retrospectively coverage-complete subset.

    Both intermittent and terminal blanks after a market's first observation cause
    a coverage exclusion. Leading blanks do not. Predeclared exclusions remain
    excluded even with complete coverage. Selection inspects missingness only;
    finite return magnitudes never determine inclusion. Input values are unchanged.

    The historical split is exposed for the course's 2015+ missingness count; the
    caller should pass its declared development boundary explicitly. The column
    ``missing_post_2014`` retains the name used by this project's report schema.
    """
    sample = _validated_sample(returns, excluded, sample_end)
    boundary = pd.Period(development_end, freq="M")
    rows = [_market_audit(name, sample[name], excluded, boundary) for name in sample]
    return pd.DataFrame(rows).set_index("market")
