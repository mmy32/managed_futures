"""Isolated, explicitly unverified endpoint assumption; never changes source files."""

import numpy as np
import pandas as pd


def apply_endpoint_assumption(returns, raw, specification):
    """Restore only declared missing cells from exact observed endpoint prices.

    The date list is fixed independently of strategy results. There is no global
    freshness relaxation, forward filling, price interpolation or future fallback.
    """
    result = returns.copy(deep=True)
    dates = [
        pd.Timestamp(specification[k])
        for k in ["previous_endpoint", "assumed_endpoint", "following_endpoint"]
    ]
    months = pd.PeriodIndex(specification["return_months"], freq="M")
    if len(months) != 2 or months[1] != months[0] + 1:
        raise ValueError("Sensitivity requires two adjacent return months")
    if [date.to_period("M") for date in dates] != [months[0] - 1, months[0], months[1]]:
        raise ValueError("Endpoint dates do not match declared monthly windows")
    changes = []
    for instrument in specification["instruments"]:
        prices = raw[instrument].Close.reindex(dates)
        if not np.isfinite(prices).all() or prices.le(0).any():
            raise ValueError(f"Missing or invalid exact endpoint price: {instrument}")
        for i, month in enumerate(months):
            if pd.notna(result.loc[month, instrument]):
                raise ValueError(
                    f"Assumption must not overwrite an observed return: {instrument} {month}"
                )
            value = prices.iloc[i + 1] / prices.iloc[i] - 1
            result.loc[month, instrument] = value
            changes.append(
                {
                    "instrument": instrument,
                    "month": str(month),
                    "prior_return": np.nan,
                    "assumed_return": value,
                    "start_price_date": str(dates[i].date()),
                    "end_price_date": str(dates[i + 1].date()),
                    "start_price": float(prices.iloc[i]),
                    "end_price": float(prices.iloc[i + 1]),
                    "status": specification["status"],
                    "applied_to_primary": False,
                    "applied_to_sensitivity": True,
                }
            )
    return result, pd.DataFrame(changes)
