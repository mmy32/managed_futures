"""Seal prospective rules and verify their snapshot, current source and historical inputs."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_files(root):
    files = []
    for folder, pattern in [
        ("src", "*.py"),
        ("scripts", "*.py"),
        ("tests", "*.py"),
        ("config", "*.json"),
    ]:
        files.extend((root / folder).rglob(pattern))
    files.extend(root / p for p in ["pyproject.toml", "docs/PROSPECTIVE_EVALUATION.md"])
    return {str(p.relative_to(root)): digest(p) for p in sorted(files)}


def check_hashes(root, hashes):
    for name, expected in hashes.items():
        path = root / name
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Missing or changed frozen input: {name}")


def reference_records(root):
    names = [
        "cost_revision_20261026",
        "band_experiment_20261026",
        "roll_sensitivity_20261026",
        "implementation_feasibility_20261026",
    ]
    references = {}
    for name in names:
        path = root / "reports" / name
        check_hashes(path, json.loads((path / "ARTIFACT_SHA256.json").read_text()))
        references[str((path / "ARTIFACT_SHA256.json").relative_to(root))] = digest(
            path / "ARTIFACT_SHA256.json"
        )
    raw = json.loads(
        (root / "reports/implementation_feasibility_20261026/output/raw_hashes.json").read_text()
    )
    check_hashes(root, raw)
    return references, raw


def seal(root, output):
    if output.exists():
        raise ValueError("Refusing to overwrite an existing freeze")
    references, raw = reference_records(root)
    files = frozen_files(root)
    protocol = json.loads((root / "config/prospective_evaluation.json").read_text())
    versions = {
        name: importlib.metadata.version(name)
        for name in ["numpy", "pandas", "scipy", "statsmodels", "openpyxl", "pytest"]
    }
    output.mkdir(parents=True)
    with zipfile.ZipFile(output / "source_snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
    record = dict(
        created_utc=datetime.now(timezone.utc).isoformat(),
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        includes_uncommitted_changes=True,
        protocol=protocol,
        files=files,
        source_snapshot_sha256=digest(output / "source_snapshot.zip"),
        reference_manifests=references,
        raw_inputs=raw,
        python=platform.python_version(),
        package_versions=versions,
        prospective_observations=0,
        independent_validation_complete=False,
    )
    (output / "freeze.json").write_text(json.dumps(record, indent=2) + "\n")
    verify(root, output)
    return record


def verify(root, release):
    record = json.loads((release / "freeze.json").read_text())
    archive_path = release / "source_snapshot.zip"
    if digest(archive_path) != record["source_snapshot_sha256"]:
        raise ValueError("Frozen source archive changed")
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != set(record["files"]):
            raise ValueError("Frozen archive membership changed")
        for name, expected in record["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError(f"Frozen archive entry changed: {name}")
    if frozen_files(root) != record["files"]:
        raise ValueError("Working source/config differs from freeze; restore or version explicitly")
    check_hashes(root, record["raw_inputs"])
    check_hashes(root, record["reference_manifests"])
    for name in record["reference_manifests"]:
        path = root / name
        check_hashes(path.parent, json.loads(path.read_text()))
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seal", "verify"])
    parser.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    result = (seal if args.action == "seal" else verify)(project, args.release.resolve())
    print(
        json.dumps(
            dict(
                status="verified",
                source_files=len(result["files"]),
                raw_inputs=len(result["raw_inputs"]),
                independent_validation_complete=False,
            )
        )
    )
