import pandas as pd
import pytest

from src.data_loader import load_monthly_returns


def _write(tmp_path, text):
    path = tmp_path / "returns.csv"
    path.write_text(text)
    return path


def test_loads_dates_and_columns(tmp_path):
    path = _write(tmp_path, ",A,B\n1/31/2000,0.01,\n2/29/2000,-0.02,0.03\n")
    result = load_monthly_returns(path)
    assert list(result.columns) == ["A", "B"]
    assert result.index.tolist() == [pd.Timestamp("2000-01-31"), pd.Timestamp("2000-02-29")]
    assert result.loc["2000-02-29", "B"] == 0.03
    assert pd.isna(result.loc["2000-01-31", "B"])


def test_rejects_unsorted_dates(tmp_path):
    path = _write(tmp_path, ",A\n2/29/2000,0.01\n1/31/2000,0.02\n")
    with pytest.raises(ValueError, match="sorted"):
        load_monthly_returns(path)


def test_rejects_duplicate_dates(tmp_path):
    path = _write(tmp_path, ",A\n1/31/2000,0.01\n1/31/2000,0.02\n")
    with pytest.raises(ValueError, match="duplicate dates"):
        load_monthly_returns(path)


def test_rejects_non_numeric_cells(tmp_path):
    path = _write(tmp_path, ",A\n1/31/2000,abc\n2/29/2000,0.02\n")
    with pytest.raises(ValueError):
        load_monthly_returns(path)


def test_rejects_all_nan_column(tmp_path):
    path = _write(tmp_path, ",A,B\n1/31/2000,0.01,\n2/29/2000,0.02,\n")
    with pytest.raises(ValueError, match="no data"):
        load_monthly_returns(path)
