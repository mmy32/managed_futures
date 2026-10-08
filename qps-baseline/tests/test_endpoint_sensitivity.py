"""A conditional data overlay must be narrow, reproducible and nonmutating."""
import copy
import numpy as np
import pandas as pd
import pytest
from endpoint_sensitivity import apply_endpoint_assumption


def inputs():
    index = pd.period_range('1997-02', '1997-05', freq='M')
    returns = pd.DataFrame(.01, index=index, columns=['DT', 'GS', 'LX', 'SS', 'OTHER'])
    returns.loc['1997-03':'1997-04', ['DT', 'GS', 'LX', 'SS']] = np.nan
    spec = dict(instruments=['DT', 'GS', 'LX', 'SS'], previous_endpoint='1997-02-28',
                assumed_endpoint='1997-03-27', following_endpoint='1997-04-30',
                return_months=['1997-03', '1997-04'], status='unverified_research_assumption')
    raw = {a: pd.DataFrame({'Close': [100., 95., 105., 999.]},
                          index=pd.to_datetime(['1997-02-28', '1997-03-27', '1997-04-30', '1997-05-01']))
           for a in spec['instruments']}
    return returns, raw, spec


def test_only_eight_missing_cells_change_and_preserved_input_is_untouched():
    original, raw, spec = inputs()
    snapshot = original.copy(deep=True)
    result, log = apply_endpoint_assumption(original, raw, spec)
    pd.testing.assert_frame_equal(original, snapshot)
    assert len(log) == 8 and not log.applied_to_primary.any()
    assert log.applied_to_sensitivity.all()
    for instrument in spec['instruments']:
        assert result.loc['1997-03', instrument] == pytest.approx(-.05)
        assert result.loc['1997-04', instrument] == pytest.approx(105/95-1)
    pd.testing.assert_frame_equal(result.where(original.notna()), original)
    pd.testing.assert_series_equal(result.OTHER, original.OTHER)


def test_assumption_rejects_overwriting_observed_return():
    original, raw, spec = inputs()
    original.loc['1997-03', 'DT'] = 0.
    with pytest.raises(ValueError, match='must not overwrite'):
        apply_endpoint_assumption(original, raw, spec)


def test_missing_exact_price_never_falls_back_to_another_day():
    original, raw, spec = inputs()
    raw['DT'] = raw['DT'].drop(pd.Timestamp('1997-03-27'))
    with pytest.raises(ValueError, match='exact endpoint price'):
        apply_endpoint_assumption(original, raw, spec)


def test_future_raw_prices_do_not_change_declared_endpoint_returns():
    original, raw, spec = inputs()
    before, _ = apply_endpoint_assumption(original, raw, spec)
    altered = copy.deepcopy(raw)
    for frame in altered.values():
        frame.loc['1997-05-01', 'Close'] = .00001
    after, _ = apply_endpoint_assumption(original, altered, spec)
    pd.testing.assert_frame_equal(before, after)


def test_assumption_cannot_bridge_nonadjacent_months():
    original, raw, spec = inputs()
    spec['return_months'] = ['1997-03', '1997-05']
    with pytest.raises(ValueError, match='adjacent'):
        apply_endpoint_assumption(original, raw, spec)
