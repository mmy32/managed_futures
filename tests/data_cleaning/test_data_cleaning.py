import json

import numpy as np
import pandas as pd
import pytest

from src.data_cleaning import (
    clean,
    combine,
    exclude,
    find_duplicate_groups,
    find_low_quality,
)
from src.data_cleaning.combine import combine_prices


@pytest.fixture
def returns() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2000-01-31", periods=80, freq="ME")
    base = rng.normal(0, 0.03, 80)
    frame = pd.DataFrame(
        {
            "A": base,
            "B": base + rng.normal(0, 1e-5, 80),  # duplicate of A
            "C": rng.normal(0, 0.03, 80),
            "SHORT": np.where(np.arange(80) < 70, np.nan, 0.01),
            "ZEROS": np.where(np.arange(80) % 2 == 0, 0.0, 0.01),
            "SPIKE": rng.normal(0, 0.03, 80),
        },
        index=idx,
    )
    frame.loc[idx[5], "SPIKE"] = 2.0
    return frame


@pytest.fixture
def asset_map() -> pd.DataFrame:
    return pd.DataFrame(
        {"AssetClass": ["EQ", "EQ", "FX", "FX", "FX", "FX"]},
        index=pd.Index(["A", "B", "C", "SHORT", "ZEROS", "SPIKE"], name="ID"),
    )


def test_find_low_quality_reasons(returns):
    flagged = find_low_quality(returns)
    assert set(flagged) == {"SHORT", "ZEROS", "SPIKE"}
    assert "observations" in flagged["SHORT"]
    assert "zero-return" in flagged["ZEROS"]
    assert "|return|" in flagged["SPIKE"]


def test_exclude_ignores_unknown_ids(returns):
    assert "A" not in exclude(returns, {"A", "NOPE"}).columns


def test_duplicate_groups_respect_min_overlap(returns):
    assert find_duplicate_groups(returns[["A", "B", "C"]]) == [["A", "B"]]
    assert find_duplicate_groups(returns[["A", "B", "C"]], min_overlap=81) == []


def test_combine_is_nan_aware_and_keeps_mapping():
    idx = pd.date_range("2000-01-31", periods=3, freq="ME")
    panel = pd.DataFrame(
        {"A": [np.nan, 0.02, 0.04], "B": [0.01, 0.04, np.nan], "C": [1.0, 1.0, 1.0]},
        index=idx,
    )
    out, mapping = combine(panel, [["A", "B"]])
    assert mapping == {"A": ["A", "B"]}  # tie on observations: first ID wins
    assert out["A"].tolist() == [0.01, 0.03, 0.04]
    assert "B" not in out.columns


def test_combine_prices_compounds_average_return():
    idx = pd.date_range("2000-01-03", periods=3, freq="D")
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0], "B": [50.0, 50.0, 50.0]}, index=idx)
    out = combine_prices(prices, {"A": ["A", "B"], "Z": ["Z"]})
    assert out["A"].tolist() == pytest.approx([1.0, 1.05, 1.05 * 1.05])
    assert "B" not in out.columns


def test_clean_applies_to_all_inputs_and_is_idempotent(returns, asset_map):
    prices = (1 + returns.fillna(0)).cumprod() * 100
    result = clean(returns, prices, asset_map)
    assert set(result.report.excluded) == {"SHORT", "ZEROS", "SPIKE"}
    assert result.report.merged == {"A": ["A", "B"]}
    assert list(result.returns.columns) == ["A", "C"]
    assert list(result.prices.columns) == ["A", "C"]
    assert list(result.asset_map.index) == ["A", "C"]

    again = clean(result.returns, result.prices, result.asset_map)
    pd.testing.assert_frame_equal(again.returns, result.returns)
    assert again.report.excluded == {} and again.report.merged == {}


def test_clean_fails_on_mixed_asset_classes(returns, asset_map):
    asset_map.loc["B", "AssetClass"] = "FX"
    with pytest.raises(ValueError, match="asset classes"):
        clean(returns, returns, asset_map)


def test_report_save_roundtrip(returns, asset_map, tmp_path):
    result = clean(returns, returns, asset_map)
    path = tmp_path / "sub" / "report.json"
    result.report.save(path)
    saved = json.loads(path.read_text())
    assert saved["merged"] == {"A": ["A", "B"]}
