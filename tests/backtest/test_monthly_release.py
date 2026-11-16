"""Published monthly reports resolve local supplied inputs from the current checkout."""

from pathlib import Path

import pandas as pd
import pytest
import run_monthly_full_sample as runner


def test_repository_input_names_are_relative_and_external_inputs_remain_explicit(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(runner, "PROJECT_ROOT", root)
    assert runner._input_name(root / "data/raw/monthly.xlsx") == "data/raw/monthly.xlsx"
    assert runner._input_name(tmp_path / "external.json") == str(tmp_path / "external.json")


def test_verification_reads_inputs_in_relocated_checkout_and_detects_changes(tmp_path, monkeypatch):
    original, clone = tmp_path / "original", tmp_path / "clone"
    relative = Path("data/raw/monthly.xlsx")
    for root in (original, clone):
        (root / relative).parent.mkdir(parents=True)
        (root / relative).write_bytes(b"supplied workbook fixture")
    record = {"inputs": {str(relative): runner.digest(original / relative)}, "source": {}}
    monkeypatch.setattr(runner, "PROJECT_ROOT", clone)
    runner.verify_fingerprints(record)
    # An unchanged original file must not conceal a changed input in this checkout.
    (clone / relative).write_bytes(b"different input")
    with pytest.raises(ValueError, match="input changed"):
        runner.verify_fingerprints(record)


def test_report_exports_describe_inputs_without_copying_supplied_returns(tmp_path):
    meta = pd.DataFrame({"AssetClass": ["COMM"]}, index=["A"])
    audit = pd.DataFrame({"included_coverage": [True]}, index=["A"])
    runner.export_inputs(tmp_path, meta, audit, {}, {}, {}, {"inputs": {}, "source": {}})
    assert (tmp_path / "universe_audit.csv").is_file()
    assert (tmp_path / "run_declaration.json").is_file()
    assert not (tmp_path / "strategy_returns.csv.gz").exists()
