"""Validate a FHIR R4 export against JLIGHT's read-only status adapter.

Use synthetic Synthea data only. This utility reports aggregate counts and never prints
resource IDs, patient references, names, dates of birth, or clinical result values.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.source_adapters import parse_source_export


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to a synthetic FHIR R4 Bundle JSON file")
    parser.add_argument("--source-system", default="synthea-synthetic")
    parser.add_argument("--domain", required=True, choices=("hospital", "laboratory", "bioinformatics"))
    args = parser.parse_args()

    path = Path(args.file)
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        events = parse_source_export("fhir", bundle, source_system=args.source_system, domain=args.domain)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 2

    event_types = Counter(event["event_type"] for event in events)
    resource_count = len(bundle.get("entry") or [])
    print("JLIGHT FHIR R4 status-metadata validation")
    print(f"Input: {path.name}")
    print(f"Domain: {args.domain}")
    print(f"Bundle resources: {resource_count}")
    print(f"Mapped workflow events: {len(events)}")
    print(f"Distinct event types: {len(event_types)}")
    for event_type, count in sorted(event_types.items()):
        print(f"  {event_type}: {count}")
    print("Patient references are transient only; this report does not display them.")
    print("No source write-back, sample processing, or clinical-result interpretation performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
