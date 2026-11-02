"""Cross-domain patient-journey reconciliation and discrepancy review.

Only records carrying an explicitly verified JLIGHT patient link are grouped.
Findings are review flags, not diagnoses or autonomous corrections.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

REQUIRED_JOURNEY_DOMAINS = ("hospital", "laboratory", "bioinformatics")
CORRELATION_FIELDS = ("encounter_id", "order_id", "specimen_id", "accession_id")


def _value(record: Mapping[str, Any], field: str) -> str | None:
    data = record.get("data") or {}
    value = data.get(field)
    if value in (None, ""):
        return None
    return str(value).strip()


def reconcile_patient_journeys(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Group verified patient records and flag cross-system integrity gaps.

    Does not infer identity. It compares correlation values only when supplied
    explicitly by source systems. A missing value is reported as incomplete
    evidence, never treated as proof of a mismatch.
    """
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    excluded = {"unlinked": 0, "clinical_trials": 0, "invalid_link": 0}
    seen: set[str] = set()
    duplicates: list[str] = []
    for record in records:
        domain = str(record.get("domain") or "").lower()
        if domain == "clinical_trials":
            excluded["clinical_trials"] += 1
            continue
        patient_id = str(record.get("jlight_patient_id") or "").strip()
        if not patient_id or record.get("link_status") != "verified":
            excluded["unlinked"] += 1
            continue
        if domain not in REQUIRED_JOURNEY_DOMAINS:
            excluded["invalid_link"] += 1
            continue
        source_key = str(record.get("source_key") or "")
        if source_key and source_key in seen:
            duplicates.append(source_key)
            continue
        if source_key:
            seen.add(source_key)
        groups[patient_id].append(record)

    journeys = []
    totals = defaultdict(int)
    for patient_id, items in sorted(groups.items()):
        by_domain: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in items:
            by_domain[str(item["domain"]).lower()].append(item)
        present = set(by_domain)
        missing = [domain for domain in REQUIRED_JOURNEY_DOMAINS if domain not in present]
        findings: list[dict[str, Any]] = []
        if missing:
            findings.append({
                "code": "journey_section_missing", "severity": "review",
                "message": "Expected patient-journey section evidence is missing.",
                "missing_domains": missing,
            })

        # Compare explicit cross-system identifiers. Never infer a link from names/DOB.
        for field in CORRELATION_FIELDS:
            observed = []
            for domain, domain_items in by_domain.items():
                values = sorted({_value(item, field) for item in domain_items} - {None})
                if values:
                    observed.append((domain, values))
            flattened = {value for _, values in observed for value in values}
            if len(flattened) > 1:
                findings.append({
                    "code": "cross_system_identifier_conflict", "severity": "high",
                    "field": field,
                    "values_by_domain": {domain: values for domain, values in observed},
                    "message": f"Source systems contain conflicting {field} values; verify before combining records.",
                })

        # A result with no explicit order or specimen reference cannot be proven
        # to belong to a particular order; flag it as incomplete, not mismatched.
        for domain in ("laboratory", "bioinformatics"):
            for item in by_domain.get(domain, []):
                correlation = [_value(item, f) for f in ("order_id", "specimen_id", "accession_id")]
                if not any(correlation):
                    findings.append({
                        "code": "source_linkage_reference_missing", "severity": "review",
                        "domain": domain, "source_key": item.get("source_key"),
                        "message": "No explicit order, specimen or accession reference was supplied.",
                    })

        # Multiple records for one patient and domain can be legitimate; only flag
        # repeated identical source keys (handled above), not multiple tests.
        cross_section = len(present) > 1
        for finding in findings:
            totals[finding["code"]] += 1
        journeys.append({
            "jlight_patient_id": patient_id,
            "records_by_domain": {d: len(v) for d, v in sorted(by_domain.items())},
            "domains_present": sorted(present),
            "missing_domains": missing,
            "cross_section": cross_section,
            "findings": findings,
            "review_required": bool(findings),
            "source_keys": sorted(str(x.get("source_key") or "") for x in items),
        })

    return {
        "journeys": journeys,
        "journey_count": len(journeys),
        "complete_three_section_journeys": sum(
            1 for j in journeys if not j["missing_domains"]
        ),
        "journeys_requiring_review": sum(1 for j in journeys if j["review_required"]),
        "finding_counts": dict(sorted(totals.items())),
        "duplicate_source_keys": sorted(set(duplicates)),
        "excluded_records": excluded,
        "clinical_trials_included": False,
        "identity_policy": "verified JLIGHT patient links only; no name/date-of-birth inference",
        "interpretation": "Findings are data-integrity review flags, not diagnoses or automatic corrections.",
    }
