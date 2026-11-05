"""Accounting and paired uncertainty for the fixed trading-band experiment."""

import numpy as np
import pandas as pd


def turnover_components(returns, exposure, ledger, source):
    """Partition actual trades; source-switch close/open legs take precedence."""
    previous = exposure.shift(1) * (1 + returns.fillna(0).shift(1))
    previous = previous.div(1 + ledger.net_return.shift(1), axis=0).fillna(0)
    switched = source.ne(source.shift(1)) & source.notna() & source.shift(1).notna()
    switched.iloc[0] = False
    traded = (exposure - previous).abs()
    traded = traded.mask(switched, exposure.abs() + previous.abs())
    masks = {
        "source_switches": switched,
        "entries": ~switched & previous.eq(0) & exposure.ne(0),
        "exits": ~switched & previous.ne(0) & exposure.eq(0),
        "reversals": ~switched & (previous * exposure).lt(0),
        "resizes": ~switched & (previous * exposure).gt(0),
    }
    result = pd.DataFrame({name: traded.where(mask, 0).sum(axis=1) for name, mask in masks.items()})
    np.testing.assert_allclose(result.sum(axis=1), ledger.rebalance_turnover, atol=1e-12)
    result["terminal_liquidation"] = ledger.terminal_turnover
    np.testing.assert_allclose(result.sum(axis=1), ledger.turnover, atol=1e-12)
    return result


def paired_bootstrap(differences, block, draws, seed, confidence=0.95, family_size=8):
    """Circular moving-block percentile intervals for annualized paired mean differences.

    All columns share each resampled calendar. Bonferroni intervals cover the
    specified comparison family approximately, for this block length only.
    """
    values = differences.to_numpy(dtype=float)
    if not np.isfinite(values).all() or len(values) < block or block < 1:
        raise ValueError("Bootstrap requires finite paired observations and a valid block")
    if draws < 1 or family_size < len(differences.columns) or not 0 < confidence < 1:
        raise ValueError("Invalid draws, confidence or comparison family")
    rng = np.random.default_rng(seed)
    n = len(values)
    estimates = np.empty((draws, values.shape[1]))
    for start in range(0, draws, 250):
        size = min(250, draws - start)
        heads = rng.integers(0, n, size=(size, (n + block - 1) // block))
        index = ((heads[:, :, None] + np.arange(block)) % n).reshape(size, -1)[:, :n]
        estimates[start : start + size] = values[index].mean(axis=1) * 12
    tail = (1 - confidence) / 2
    bounds = np.quantile(
        estimates, [tail, 1 - tail, tail / family_size, 1 - tail / family_size], axis=0
    )
    return pd.DataFrame(
        {
            "mean_difference_ann": values.mean(axis=0) * 12,
            "ci_low": bounds[0],
            "ci_high": bounds[1],
            "family_ci_low": bounds[2],
            "family_ci_high": bounds[3],
            "block_months": block,
            "draws": draws,
            "family_size": family_size,
        },
        index=differences.columns,
    )
