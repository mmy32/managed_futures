import pandas as pd
import pytest

from construct_returns import assemble
from src.data_processing.endpoints import close_frames, endpoints, historical_span_endpoints


def test_close_frames_restores_each_markets_own_history():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    prices = pd.DataFrame({"A": [1.0, 2.0, None], "B": [None, 5.0, 6.0]}, index=dates)

    frames = close_frames(prices)

    assert list(frames["A"].index) == list(dates[:2])
    assert list(frames["B"].index) == list(dates[1:])
    assert list(frames["B"].columns) == ["Close"]
    assert frames["B"].Close.tolist() == [5.0, 6.0]


def test_endpoint_does_not_change_when_a_later_close_is_appended():
    months = pd.period_range("2024-03", "2024-03", freq="M")
    prefix = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-03-28"]))
    full = pd.DataFrame(
        {"Close": [100.0, 101.0]}, index=pd.to_datetime(["2024-03-28", "2024-04-01"])
    )
    before, after = endpoints(prefix, months), endpoints(full, months)
    pd.testing.assert_frame_equal(before, after)
    assert before.iloc[0].endpoint_accepted
    assert before.iloc[0].endpoint_close == 100.0
    # The historical reconciliation rule deliberately retains the old behavior.
    assert not historical_span_endpoints(prefix, months).iloc[0].endpoint_accepted
    assert historical_span_endpoints(full, months).iloc[0].endpoint_accepted


def test_endpoint_rejects_stale_closes_and_never_exposes_a_future_close():
    data = pd.DataFrame(
        {"Close": [100.0, 101.0]}, index=pd.to_datetime(["2024-03-25", "2024-04-30"])
    )
    months = pd.period_range("2024-02", "2024-04", freq="M")
    result = endpoints(data, months)
    assert pd.isna(result.loc["2024-02", "raw_close"])
    assert pd.isna(result.loc["2024-02", "endpoint_close"])
    assert not result.loc["2024-03", "endpoint_accepted"]  # four calendar days old
    assert result.loc["2024-04", "endpoint_close"] == 101.0


def test_endpoint_rejects_empty_or_unordered_price_history():
    months = pd.period_range("2024-03", "2024-03", freq="M")
    with pytest.raises(ValueError, match="nonempty, ordered, unique"):
        endpoints(pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([])), months)
    data = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2024-03-29", "2024-03-28"]))
    with pytest.raises(ValueError, match="nonempty, ordered, unique"):
        endpoints(data, months)


def test_strategy_return_construction_does_not_use_historical_span_rule():
    months = pd.period_range("2024-02", "2024-03", freq="M")
    prefix = pd.DataFrame(
        {"Close": [90.0, 100.0]}, index=pd.to_datetime(["2024-02-29", "2024-03-28"])
    )
    full = pd.concat(
        [prefix, pd.DataFrame({"Close": [101.0]}, index=pd.to_datetime(["2024-04-01"]))]
    )
    before = {name: prefix for name in ["A", "RL", "ER"]}
    after = {name: full for name in before}
    expected, _, _ = assemble(before, months, ["A", "RL"])
    result, _, _ = assemble(after, months, ["A", "RL"])
    pd.testing.assert_frame_equal(expected, result)
    assert expected.loc["2024-03", "A"] == pytest.approx(100 / 90 - 1)
    historical, _, _ = assemble(before, months, ["A", "RL"], historical_reproduction=True)
    assert pd.isna(historical.loc["2024-03", "A"])
