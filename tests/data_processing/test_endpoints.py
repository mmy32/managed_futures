import pandas as pd

from src.data_processing.endpoints import close_frames


def test_close_frames_restores_each_markets_own_history():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    prices = pd.DataFrame({"A": [1.0, 2.0, None], "B": [None, 5.0, 6.0]}, index=dates)

    frames = close_frames(prices)

    assert list(frames["A"].index) == list(dates[:2])
    assert list(frames["B"].index) == list(dates[1:])
    assert list(frames["B"].columns) == ["Close"]
    assert frames["B"].Close.tolist() == [5.0, 6.0]
