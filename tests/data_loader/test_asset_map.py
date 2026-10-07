import pytest

from src.data_loader import load_asset_map


def _write(tmp_path, text):
    path = tmp_path / "map.csv"
    path.write_text(text)
    return path


def test_loads_indexed_by_id(tmp_path):
    path = _write(tmp_path, "ID,Name,Ccy,AssetClass\nAN,Aussie,USD,FX\nUS,TBonds,USD,FI\n")
    result = load_asset_map(path)
    assert list(result.index) == ["AN", "US"]
    assert result.loc["US", "AssetClass"] == "FI"


def test_rejects_duplicate_ids(tmp_path):
    path = _write(tmp_path, "ID,Name,Ccy,AssetClass\nAN,Aussie,USD,FX\nAN,Other,USD,FX\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_asset_map(path)


def test_rejects_unknown_asset_class(tmp_path):
    path = _write(tmp_path, "ID,Name,Ccy,AssetClass\nAN,Aussie,USD,CRYPTO\n")
    with pytest.raises(ValueError, match="CRYPTO"):
        load_asset_map(path)
