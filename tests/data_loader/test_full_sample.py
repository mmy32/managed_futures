import hashlib
from datetime import datetime
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from src.data_loader import load_full_sample_returns


def workbook(tmp_path, rows, header=(None, "A", "B")):
    path = tmp_path / "returns.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    book.save(path)
    book.close()
    return path


def test_loads_declared_decimals_and_preserves_missing_values_and_original_bytes(tmp_path):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 0.01, None),
                               (datetime(2020, 2, 28), 1.2, -0.3)])
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    result = load_full_sample_returns(path, units="decimal")
    expected = pd.DataFrame({"A": [0.01, 1.2], "B": [float("nan"), -0.3]},
                            index=pd.period_range("2020-01", "2020-02", freq="M", name="month"))
    pd.testing.assert_frame_equal(result, expected)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_preserves_an_entire_unknown_month_without_filling(tmp_path):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 0.01, 0.02),
                               (datetime(2020, 2, 28), None, None),
                               (datetime(2020, 3, 31), 0.03, 0.04)])
    result = load_full_sample_returns(path, units="decimal")
    assert result.loc["2020-02"].isna().all()


@pytest.mark.parametrize("units", ["percent", "basis_points", "auto", "", None])
def test_rejects_undeclared_or_unsupported_units_without_scaling(tmp_path, units):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 1.5, 2.0)])
    with pytest.raises(ValueError, match="units='decimal'"):
        load_full_sample_returns(path, units=units)
    with pytest.raises(TypeError):
        load_full_sample_returns(path)


@pytest.mark.parametrize("value, error, message", [
    ("1.5%", TypeError, "numeric decimal"), ("0.015", TypeError, "numeric decimal"),
    (True, TypeError, "numeric decimal"), ("=1/100", ValueError, "formulas"),
    (-1.0, ValueError, "greater than -1"), (-1.5, ValueError, "greater than -1"),
    ("#DIV/0!", TypeError, "numeric decimal"),
])
def test_rejects_non_numeric_formulas_and_impossible_simple_returns(tmp_path, value, error, message):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), value, 0.01)])
    with pytest.raises(error, match=message):
        load_full_sample_returns(path, units="decimal")


def replace_numeric_xml(path, value):
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    key = "xl/worksheets/sheet1.xml"
    root = ElementTree.fromstring(files[key])
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cell = root.find(".//s:c[@r='B2']", ns)
    cell.find("s:v", ns).text = value
    files[key] = ElementTree.tostring(root)
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_rejects_a_formula_even_when_the_workbook_has_a_cached_numeric_value(tmp_path):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), "=1/100", 0.02)])
    replace_numeric_xml(path, "0.01")
    cached = load_workbook(path, read_only=True, data_only=True)
    assert cached["Sheet1"]["B2"].value == 0.01
    cached.close()
    with pytest.raises(ValueError, match="formulas"):
        load_full_sample_returns(path, units="decimal")


@pytest.mark.parametrize("value", ["1e999", "-1e999"])
def test_rejects_nonfinite_numeric_cells(tmp_path, value):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 0.01, 0.02)])
    replace_numeric_xml(path, value)
    with pytest.raises(ValueError, match="finite"):
        load_full_sample_returns(path, units="decimal")


@pytest.mark.parametrize("value, message", [
    ("01/31/2020", "native Excel date"), (43861, "native Excel date"),
    (datetime(2020, 1, 15), "last weekday"),
    (datetime(2020, 1, 31, 12), "without time"), (None, "native Excel date"),
])
def test_rejects_ambiguous_or_wrong_monthly_dates(tmp_path, value, message):
    path = workbook(tmp_path, [(value, 0.01, 0.02)])
    with pytest.raises(ValueError, match=message):
        load_full_sample_returns(path, units="decimal")


@pytest.mark.parametrize("dates, message", [
    ([datetime(2020, 2, 28), datetime(2020, 1, 31)], "sorted ascending"),
    ([datetime(2020, 1, 31), datetime(2020, 1, 31)], "duplicate months"),
    ([datetime(2020, 1, 31), datetime(2020, 3, 31)], "missing months"),
])
def test_rejects_unordered_duplicate_or_missing_months(tmp_path, dates, message):
    path = workbook(tmp_path, [(value, 0.01, 0.02) for value in dates])
    with pytest.raises(ValueError, match=message):
        load_full_sample_returns(path, units="decimal")


@pytest.mark.parametrize("header, message", [
    ((None, "A", "A"), "duplicate market IDs"),
    ((None, "A", None), "market IDs"),
    ((None, "A", "B B"), "market IDs"),
    (("Returns (%)", "A", "B"), "blank/Date header"),
])
def test_rejects_wrong_headers_and_duplicate_market_ids(tmp_path, header, message):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 0.01, 0.02)], header)
    with pytest.raises(ValueError, match=message):
        load_full_sample_returns(path, units="decimal")


def test_rejects_empty_columns_and_missing_declared_sheet(tmp_path):
    path = workbook(tmp_path, [(datetime(2020, 1, 31), 0.01, None)])
    with pytest.raises(ValueError, match="columns with no data"):
        load_full_sample_returns(path, units="decimal")
    with pytest.raises(ValueError, match="missing declared sheet"):
        load_full_sample_returns(path, units="decimal", sheet_name="Other")
