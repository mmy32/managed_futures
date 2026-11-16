import json

import pytest
from verify_research import digest, main, source_hashes, verify_existing


def record(output, supplied):
    output.mkdir()
    result = output / "SUMMARY.md"
    result.write_text("verified evidence\n")
    manifest = {"inputs": {str(supplied): digest(supplied)}, "source_sha256": source_hashes(),
                "outputs": {"SUMMARY.md": digest(result)}}
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_saved_verification_detects_changed_results_and_inputs(tmp_path):
    supplied = tmp_path / "input.csv"
    supplied.write_text("original input\n")
    output = tmp_path / "report"
    record(output, supplied)
    assert verify_existing(output) == 1
    (output / "SUMMARY.md").write_text("changed evidence\n")
    with pytest.raises(ValueError, match="Saved output changed"):
        verify_existing(output)
    (output / "SUMMARY.md").write_text("verified evidence\n")
    supplied.write_text("changed input\n")
    with pytest.raises(ValueError, match="Input changed"):
        verify_existing(output)


def test_saved_verification_detects_changed_implementation(tmp_path, monkeypatch):
    supplied = tmp_path / "input.csv"
    supplied.write_text("input\n")
    output = tmp_path / "report"
    record(output, supplied)
    monkeypatch.setattr("verify_research.source_hashes", lambda: {"different.py": "changed"})
    with pytest.raises(ValueError, match="Source or configuration changed"):
        verify_existing(output)


def test_verification_refuses_to_overwrite_a_report(tmp_path, monkeypatch):
    marker = tmp_path / "user.txt"
    marker.write_text("retain this")
    monkeypatch.setattr("sys.argv", ["verify_research.py", "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="never overwritten"):
        main()
    assert marker.read_text() == "retain this"
