import hashlib
import json
import zipfile

import pytest

from freeze_prospective import digest, frozen_files, seal, verify


def fixture_release(tmp_path):
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "config/rules.json").write_text('{"band":0.1}')
    (root / "docs/PROSPECTIVE_EVALUATION.md").write_text("Frozen protocol")
    (root / "pyproject.toml").write_text("# fixture")
    (root / "raw.csv").write_text("historical input")
    (root / "reference").mkdir()
    (root / "reference/result.csv").write_text("historical result")
    (root / "reference/ARTIFACT_SHA256.json").write_text(
        json.dumps({"result.csv": digest(root / "reference/result.csv")})
    )
    release = tmp_path / "release"
    release.mkdir()
    files = frozen_files(root)
    with zipfile.ZipFile(release / "source_snapshot.zip", "w") as archive:
        for name in files:
            archive.write(root / name, name)
    record = dict(
        files=files,
        source_snapshot_sha256=digest(release / "source_snapshot.zip"),
        raw_inputs={"raw.csv": digest(root / "raw.csv")},
        reference_manifests={
            "reference/ARTIFACT_SHA256.json": digest(root / "reference/ARTIFACT_SHA256.json")
        },
    )
    (release / "freeze.json").write_text(json.dumps(record))
    return root, release


@pytest.mark.parametrize("change", ["config", "added_code", "raw", "reference", "archive"])
def test_freeze_detects_changed_rules_data_history_and_archive(tmp_path, change):
    root, release = fixture_release(tmp_path)
    verify(root, release)
    if change == "config":
        (root / "config/rules.json").write_text('{"band":0}')
    elif change == "added_code":
        (root / "src").mkdir()
        (root / "src/new.py").write_text("new_rule = True")
    elif change == "raw":
        (root / "raw.csv").write_text("revised input")
    elif change == "reference":
        (root / "reference/result.csv").write_text("revised result")
    else:
        with zipfile.ZipFile(release / "source_snapshot.zip", "a") as archive:
            archive.writestr("extra.py", "changed")
        record = json.loads((release / "freeze.json").read_text())
        record["source_snapshot_sha256"] = digest(release / "source_snapshot.zip")
        (release / "freeze.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        verify(root, release)


def test_freeze_preserves_snapshot_and_refuses_overwrite(tmp_path):
    root, release = fixture_release(tmp_path)
    before = hashlib.sha256((release / "source_snapshot.zip").read_bytes()).hexdigest()
    verify(root, release)
    with pytest.raises(ValueError, match="overwrite"):
        seal(root, release)
    assert digest(release / "source_snapshot.zip") == before
