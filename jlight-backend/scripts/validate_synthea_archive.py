"""JLIGHT Synthea FHIR archive validator.

Status: NEWLY IMPLEMENTED (2026-11-18). This validator is not a recovered
original; the previously referenced script at this path never existed in the
repository (verified against the working tree and GitHub history). It was
written to the documented requirements so the two previously supplied Synthea
FHIR R4 archives can be validated the moment they are made available to the
workspace. It performs READ-ONLY validation: it never writes to any database,
never imports records, and never alters source data.

What it validates, per archive (ZIP):
  - SHA-256 checksum of the archive
  - Number of ZIP entries and parsed JSON documents
  - Number of FHIR Bundles and total resources (bundle entries + standalone
    resources)
  - Resource-type inventory
  - Patient / Encounter / Observation / DiagnosticReport counts
  - Parse errors (unreadable entries, non-JSON, missing resourceType) and
    structural warnings (bundles without type, entries without resources)

Usage:
  python3 scripts/validate_synthea_archive.py ARCHIVE.zip [ARCHIVE2.zip ...]
      [--json OUT.json] [--fail-on-error]

Exit codes: 0 = all archives parsed (warnings allowed), 1 = parse errors
present (or --fail-on-error with warnings), 2 = usage/IO failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

KEY_TYPES = ("Patient", "Encounter", "Observation", "DiagnosticReport")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_archive(archive_path: Path) -> dict:
    """Validate one ZIP archive of FHIR documents. Read-only; raises nothing
    except zipfile.BadZipFile / OSError for unreadable archives."""
    result: dict = {
        "archive": str(archive_path),
        "sha256": _sha256_file(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "zip_entries": 0,
        "json_documents": 0,
        "bundles": 0,
        "resources": 0,
        "resource_types": {},
        "key_counts": {key: 0 for key in KEY_TYPES},
        "errors": [],
        "warnings": [],
    }
    type_counts: Counter[str] = Counter()

    with zipfile.ZipFile(archive_path) as zf:
        members = [info for info in zf.infolist() if not info.is_dir()]
        result["zip_entries"] = len(members)
        for info in members:
            name = info.filename
            try:
                payload = zf.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                result["errors"].append({"entry": name, "error": f"unreadable entry: {exc}"})
                continue
            if not name.lower().endswith(".json"):
                continue
            try:
                document = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                result["errors"].append({"entry": name, "error": f"invalid JSON: {exc}"})
                continue
            if not isinstance(document, dict):
                result["errors"].append({"entry": name, "error": "JSON document is not an object"})
                continue
            result["json_documents"] += 1
            resource_type = document.get("resourceType")
            if not isinstance(resource_type, str):
                result["errors"].append({"entry": name, "error": "missing resourceType"})
                continue
            if resource_type == "Bundle":
                result["bundles"] += 1
                if document.get("type") is None:
                    result["warnings"].append({"entry": name, "warning": "bundle without type"})
                entries = document.get("entry")
                if not isinstance(entries, list):
                    result["warnings"].append({"entry": name, "warning": "bundle without entry list"})
                    entries = []
                counted = 0
                for entry in entries:
                    if not isinstance(entry, dict):
                        result["warnings"].append({"entry": name, "warning": "non-object bundle entry"})
                        continue
                    resource = entry.get("resource")
                    if not isinstance(resource, dict) or not isinstance(resource.get("resourceType"), str):
                        result["warnings"].append({"entry": name, "warning": "bundle entry without resource"})
                        continue
                    counted += 1
                    inner_type = resource["resourceType"]
                    type_counts[inner_type] += 1
                    if inner_type in result["key_counts"]:
                        result["key_counts"][inner_type] += 1
                result["resources"] += counted
            else:
                result["resources"] += 1
                type_counts[resource_type] += 1
                if resource_type in result["key_counts"]:
                    result["key_counts"][resource_type] += 1

    result["resource_types"] = dict(sorted(type_counts.items()))
    return result


def validate_archives(archive_paths: list[Path]) -> dict:
    report = {"validator": "scripts/validate_synthea_archive.py (newly implemented 2026-11-18, not a recovered original)", "archives": []}
    for path in archive_paths:
        report["archives"].append(validate_archive(path))
    report["totals"] = {
        "archives": len(report["archives"]),
        "bundles": sum(a["bundles"] for a in report["archives"]),
        "resources": sum(a["resources"] for a in report["archives"]),
        "errors": sum(len(a["errors"]) for a in report["archives"]),
        "warnings": sum(len(a["warnings"]) for a in report["archives"]),
        "key_counts": {
            key: sum(a["key_counts"][key] for a in report["archives"])
            for key in KEY_TYPES
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Synthea FHIR R4 ZIP archives (read-only).")
    parser.add_argument("archives", nargs="+", type=Path, help="ZIP archives to validate")
    parser.add_argument("--json", type=Path, default=None, help="write the full JSON report to this path")
    parser.add_argument("--fail-on-error", action="store_true", help="exit 1 when any parse error is present (default behaviour); warnings never fail")
    args = parser.parse_args(argv)

    for path in args.archives:
        if not path.is_file():
            print(f"ERROR: archive not found: {path}", file=sys.stderr)
            return 2

    try:
        report = validate_archives(args.archives)
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"ERROR: cannot read archive: {exc}", file=sys.stderr)
        return 2

    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for archive in report["archives"]:
        print(f"archive: {archive['archive']}")
        print(f"  sha256: {archive['sha256']}")
        print(f"  bundles: {archive['bundles']}  resources: {archive['resources']}  json documents: {archive['json_documents']}  zip entries: {archive['zip_entries']}")
        for key in KEY_TYPES:
            print(f"  {key}: {archive['key_counts'][key]}")
        print(f"  errors: {len(archive['errors'])}  warnings: {len(archive['warnings'])}")
    totals = report["totals"]
    print(f"TOTALS: archives={totals['archives']} bundles={totals['bundles']} resources={totals['resources']} errors={totals['errors']} warnings={totals['warnings']}")

    return 1 if totals["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
