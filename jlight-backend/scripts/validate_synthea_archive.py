"""Reproducibly validate a ZIP of synthetic Synthea FHIR R4 Bundles with JLIGHT's exact adapter.

Only aggregate metadata is emitted. No resource identifiers, patient references, dates of birth,
or clinical values are printed. Intended for synthetic data only.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import PurePosixPath

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from engine.source_adapters import parse_source_export


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, help="ZIP containing synthetic FHIR Bundle JSON files")
    parser.add_argument("--domain", default="hospital", choices=("hospital", "laboratory", "bioinformatics"))
    parser.add_argument("--source-system", default="synthea-synthetic")
    parser.add_argument("--max-files", type=int, default=0, help="Optional limit; 0 means all JSON files")
    args = parser.parse_args()
    if args.max_files < 0:
        parser.error("--max-files must be zero or a positive integer")

    files_seen = bundles_seen = resources_seen = mapped_events = 0
    resources_by_type: Counter[str] = Counter()
    events_by_type: Counter[str] = Counter()
    unmapped_by_type: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    try:
        with zipfile.ZipFile(args.zip) as archive:
            names = sorted(n for n in archive.namelist()
                           if not n.endswith("/") and PurePosixPath(n).suffix.lower() == ".json")
            if args.max_files:
                names = names[:args.max_files]
            if not names:
                print("VALIDATION FAILED: ZIP contains no JSON files", file=sys.stderr)
                return 2
            for name in names:
                files_seen += 1
                try:
                    bundle = json.loads(archive.read(name))
                    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
                        errors["not_bundle"] += 1
                        continue
                    bundles_seen += 1
                    entries = bundle.get("entry") or []
                    resources_seen += len(entries) if isinstance(entries, list) else 0
                    for entry in entries if isinstance(entries, list) else []:
                        resource = entry.get("resource") if isinstance(entry, dict) else None
                        if isinstance(resource, dict):
                            resources_by_type[str(resource.get("resourceType") or "missing_type")] += 1
                            if resource.get("resourceType") in {"Encounter", "ServiceRequest", "Task", "DiagnosticReport"}:
                                status = str(resource.get("status") or "").lower()
                                # Count potential candidates separately; the adapter remains the authority.
                                if status:
                                    unmapped_by_type[str(resource.get("resourceType"))] += 0
                    events = parse_source_export("fhir", bundle,
                        source_system=args.source_system, domain=args.domain)
                    mapped_events += len(events)
                    events_by_type.update(str(e.get("event_type") or "missing_event_type") for e in events)
                except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
                    errors["invalid_or_rejected_bundle"] += 1
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"VALIDATION FAILED: cannot read ZIP ({type(exc).__name__})", file=sys.stderr)
        return 2

    print("JLIGHT exact-package synthetic FHIR archive validation")
    print(f"Input archive: {PurePosixPath(args.zip).name}")
    print(f"Domain: {args.domain}")
    print(f"JSON files examined: {files_seen}")
    print(f"Valid Bundle files: {bundles_seen}")
    print(f"Resources in valid Bundles: {resources_seen}")
    print(f"Mapped workflow events: {mapped_events}")
    print("Resource types (aggregate):")
    for name, count in sorted(resources_by_type.items()):
        print(f"  {name}: {count}")
    print("Mapped event types (aggregate):")
    for name, count in sorted(events_by_type.items()):
        print(f"  {name}: {count}")
    print("Rejected/invalid files (aggregate):")
    for name, count in sorted(errors.items()):
        print(f"  {name}: {count}")
    print("No patient references or clinical values printed; no source write-back performed.")
    if errors or bundles_seen != files_seen:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
