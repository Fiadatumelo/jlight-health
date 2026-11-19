"""Regression tests for scripts/validate_synthea_archive.py.

The validator at that path is NEWLY IMPLEMENTED (2026-11-18, see its module
docstring). These tests exercise it against small synthetic FHIR R4 fixtures so
its counting, checksumming and error handling are verified before it is ever
run against the real Synthea archives. They are validation-tool tests only:
they never touch any database and never import any record.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_synthea_archive as validator  # noqa: E402


def _bundle(bundle_id: str, resources: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "searchset",
        "entry": [{"resource": resource} for resource in resources],
    }


def _patient(pid: str) -> dict:
    return {"resourceType": "Patient", "id": pid}


def _encounter(eid: str) -> dict:
    return {"resourceType": "Encounter", "id": eid}


def _observation(oid: str) -> dict:
    return {"resourceType": "Observation", "id": oid}


def _report(rid: str) -> dict:
    return {"resourceType": "DiagnosticReport", "id": rid}


def _make_zip(path: Path, documents: list[dict | str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for index, document in enumerate(documents):
            payload = document if isinstance(document, (bytes, str)) else json.dumps(document).encode("utf-8")
            zf.writestr(f"doc_{index}.json", payload)


def test_counts_bundles_and_resources(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    _make_zip(archive, [
        _bundle("b1", [_patient("p1"), _encounter("e1"), _observation("o1"), _report("r1")]),
        _bundle("b2", [_patient("p2"), _observation("o2")]),
        _patient("p3"),
    ])
    report = validator.validate_archive(archive)
    assert report["bundles"] == 2
    assert report["resources"] == 7
    assert report["key_counts"]["Patient"] == 3
    assert report["key_counts"]["Encounter"] == 1
    assert report["key_counts"]["Observation"] == 2
    assert report["key_counts"]["DiagnosticReport"] == 1
    assert report["resource_types"].get("Patient") == 3
    assert report["errors"] == []


def test_checksum_and_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "sample.zip"
    _make_zip(archive, [_bundle("b1", [_patient("p1")])])
    report = validator.validate_archive(archive)
    assert report["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert report["zip_entries"] == 1
    assert report["json_documents"] == 1


def test_detects_errors_and_reports_them(tmp_path: Path) -> None:
    archive = tmp_path / "broken.zip"
    _make_zip(archive, [
        _bundle("b1", [_patient("p1")]),
        "{not json",
        {"id": "no-resource-type"},
        [1, 2, 3],
    ])
    report = validator.validate_archive(archive)
    kinds = [error["error"] for error in report["errors"]]
    assert any("invalid JSON" in kind for kind in kinds)
    assert any("missing resourceType" in kind for kind in kinds)
    assert any("not an object" in kind for kind in kinds)
    assert report["bundles"] == 1


def test_empty_bundle_and_entry_warnings(tmp_path: Path) -> None:
    archive = tmp_path / "warn.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("w1.json", json.dumps({"resourceType": "Bundle", "type": "collection"}))
        zf.writestr("w2.json", json.dumps({"resourceType": "Bundle", "type": "searchset", "entry": [{"display": "x"}]}))
    report = validator.validate_archive(archive)
    assert report["bundles"] == 2
    assert report["resources"] == 0
    assert len(report["warnings"]) == 2


def test_totals_across_archives(tmp_path: Path) -> None:
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    _make_zip(first, [_bundle("b1", [_patient("p1"), _observation("o1")])])
    _make_zip(second, [_bundle("b2", [_patient("p2"), _encounter("e2"), _report("r2")])])
    report = validator.validate_archives([first, second])
    assert report["totals"]["archives"] == 2
    assert report["totals"]["bundles"] == 2
    assert report["totals"]["resources"] == 5
    assert report["totals"]["key_counts"]["Patient"] == 2
    assert report["totals"]["key_counts"]["Encounter"] == 1
    assert report["totals"]["key_counts"]["Observation"] == 1
    assert report["totals"]["key_counts"]["DiagnosticReport"] == 1
    assert report["totals"]["errors"] == 0


def test_cli_exit_codes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "good.zip"
    bad = tmp_path / "bad.zip"
    _make_zip(good, [_bundle("b1", [_patient("p1")])])
    _make_zip(bad, ["{broken"])
    assert validator.main([str(good), "--json", str(tmp_path / "out.json")]) == 0
    assert validator.main([str(bad)]) == 1
    assert validator.main([str(tmp_path / "missing.zip")]) == 2
    saved = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert saved["archives"][0]["sha256"] == hashlib.sha256(good.read_bytes()).hexdigest()
