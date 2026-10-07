import pandas as pd
import pytest

from src.data_loader import load_daily_prices

HEADER = ",Open,High,Low,Close,Volume,OpenInterest\n"


def _market(directory, name, rows):
    body = "".join(f"{d},1,1,1,{c},1,1\n" for d, c in rows)
    (directory / f"{name}.csv").write_text(HEADER + body)


def test_loads_close_panel_on_union_of_dates(tmp_path):
    _market(tmp_path, "AA", [("2000-01-03", 10.0), ("2000-01-04", 11.0)])
    _market(tmp_path, "BB", [("2000-01-04", 5.0), ("2000-01-05", 6.0)])
    result = load_daily_prices(tmp_path)
    assert list(result.columns) == ["AA", "BB"]
    assert len(result) == 3
    assert result.loc["2000-01-04", "AA"] == 11.0
    assert pd.isna(result.loc["2000-01-03", "BB"])


def test_rejects_duplicate_dates(tmp_path):
    _market(tmp_path, "AA", [("2000-01-03", 10.0), ("2000-01-03", 11.0)])
    with pytest.raises(ValueError, match="duplicate"):
        load_daily_prices(tmp_path)


def test_rejects_unsorted_dates(tmp_path):
    _market(tmp_path, "AA", [("2000-01-04", 10.0), ("2000-01-03", 11.0)])
    with pytest.raises(ValueError, match="sorted"):
        load_daily_prices(tmp_path)


def test_rejects_non_positive_close(tmp_path):
    _market(tmp_path, "AA", [("2000-01-03", 10.0), ("2000-01-04", 0.0)])
    with pytest.raises(ValueError, match="non-positive"):
        load_daily_prices(tmp_path)


def test_rejects_empty_directory(tmp_path):
    with pytest.raises(ValueError, match="no CSV"):
        load_daily_prices(tmp_path)
