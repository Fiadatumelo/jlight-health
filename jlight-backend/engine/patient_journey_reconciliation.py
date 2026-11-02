"""Cross-domain patient-journey reconciliation using explicit source relationships.

Only exact, verified JLIGHT patient UUID links are grouped. Relationship checks
are performed per source row using canonical foreign keys and accession values;
patient-wide identifier-set comparisons are deliberately avoided.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

REQUIRED_JOURNEY_DOMAINS = ("hospital", "laboratory", "bioinformatics")


def _value(record: Mapping[str, Any], field: str) -> str | None:
    data = record.get("data") or {}
    value = data.get(field)
    if value in (None, ""):
        return None
    return str(value).strip()


def reconcile_patient_journeys(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reconcile exact Hospital→Lab order→sample→Bioinformatics accession edges.

    Expected data fields:
      hospital: lab_order_id (UUID of jl_lab_orders.id)
      laboratory order: order_id (UUID of jl_lab_orders.id)
      laboratory sample: order_id (UUID), accession_id (accession_no)
      bioinformatics accession/run: accession_id (accession_no)

    Missing references are incomplete evidence. A supplied reference that does
    not resolve inside this patient's verified, organisation-scoped rows is a
    relationship discrepancy. No demographic or patient-wide set matching.
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
        missing = [d for d in REQUIRED_JOURNEY_DOMAINS if d not in present]
        findings: list[dict[str, Any]] = []
        if missing:
            findings.append({
                "code": "journey_section_missing", "severity": "review",
                "message": "Expected patient-journey section evidence is missing.",
                "missing_domains": missing,
            })

        lab_orders = {
            str((r.get("data") or {}).get("order_id") or r.get("source_key", "").rsplit("::", 1)[-1])
            for r in by_domain.get("laboratory", [])
            if str(r.get("source_key", "")).split("::")[-2:-1] == ["order"]
        }
        # Source rows from the API use laboratory::order::<UUID>; keep only order rows.
        if not lab_orders:
            lab_orders = {
                str(r.get("data", {}).get("order_id"))
                for r in by_domain.get("laboratory", [])
                if r.get("data", {}).get("record_type") == "order" and r.get("data", {}).get("order_id")
            }
        bio_accessions = {
            _value(r, "accession_id")
            for r in by_domain.get("bioinformatics", [])
            if _value(r, "accession_id")
        }
        lab_samples = [
            r for r in by_domain.get("laboratory", [])
            if str(r.get("source_key", "")).split("::")[-2:-1] == ["sample"]
        ]

        def flag(code: str, severity: str, record: Mapping[str, Any], message: str, field: str):
            findings.append({
                "code": code, "severity": severity, "field": field,
                "domain": record.get("domain"), "source_key": record.get("source_key"),
                "reference": _value(record, field), "message": message,
            })

        for record in by_domain.get("hospital", []):
            ref = _value(record, "order_id")
            if not ref:
                flag("source_linkage_reference_missing", "review", record,
                     "Hospital order has no linked laboratory order reference.", "order_id")
            elif ref not in lab_orders:
                flag("hospital_order_unmatched", "high", record,
                     "Hospital order reference does not resolve to a laboratory order for this patient.", "order_id")

        for record in lab_samples:
            order_ref = _value(record, "order_id")
            accession_ref = _value(record, "accession_id")
            if not order_ref:
                flag("source_linkage_reference_missing", "review", record,
                     "Laboratory sample has no order reference.", "order_id")
            elif order_ref not in lab_orders:
                flag("sample_order_unmatched", "high", record,
                     "Sample order reference does not resolve to a laboratory order for this patient.", "order_id")
            if not accession_ref:
                flag("source_linkage_reference_missing", "review", record,
                     "Laboratory sample has no accession reference.", "accession_id")
            elif accession_ref not in bio_accessions:
                flag("sample_accession_unmatched", "high", record,
                     "Sample accession does not resolve to a Bioinformatics accession for this patient.", "accession_id")

        for record in by_domain.get("bioinformatics", []):
            # Accession rows are the canonical accession inventory. Runs reference
            # those rows by FK in storage; the API projects the joined accession_no.
            if str(record.get("source_key", "")).split("::")[-2:-1] == ["run"]:
                accession_ref = _value(record, "accession_id")
                if not accession_ref:
                    flag("source_linkage_reference_missing", "review", record,
                         "Bioinformatics run has no accession reference.", "accession_id")
                elif accession_ref not in bio_accessions:
                    flag("run_accession_unmatched", "high", record,
                         "Bioinformatics run accession does not resolve to this patient's accession.", "accession_id")

        for domain in ("laboratory", "bioinformatics"):
            for record in by_domain.get(domain, []):
                kind = str(record.get("source_key", "")).split("::")[-2:-1]
                if kind == ["order"] and not _value(record, "order_id"):
                    flag("source_linkage_reference_missing", "review", record,
                         "Laboratory order reference is unavailable.", "order_id")
                if domain == "bioinformatics" and kind == ["accession"] and not _value(record, "accession_id"):
                    flag("source_linkage_reference_missing", "review", record,
                         "Bioinformatics accession reference is unavailable.", "accession_id")

        for finding in findings:
            totals[finding["code"]] += 1
        journeys.append({
            "jlight_patient_id": patient_id,
            "records_by_domain": {d: len(v) for d, v in sorted(by_domain.items())},
            "domains_present": sorted(present),
            "missing_domains": missing,
            "cross_section": len(present) > 1,
            "findings": findings,
            "review_required": bool(findings),
            "source_keys": sorted(str(x.get("source_key") or "") for x in items),
        })

    return {
        "journeys": journeys,
        "journey_count": len(journeys),
        "complete_three_section_journeys": sum(1 for j in journeys if not j["missing_domains"]),
        "journeys_requiring_review": sum(1 for j in journeys if j["review_required"]),
        "finding_counts": dict(sorted(totals.items())),
        "duplicate_source_keys": sorted(set(duplicates)),
        "excluded_records": excluded,
        "clinical_trials_included": False,
        "identity_policy": "verified JLIGHT patient links only; no name/date-of-birth inference",
        "relationship_policy": "exact organisation-scoped order and accession references; no patient-wide set matching",
        "interpretation": "Findings are data-integrity review flags, not diagnoses or automatic corrections.",
    }
