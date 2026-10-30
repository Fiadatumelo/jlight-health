"""JLIGHT Intelligence Engine — evidence-first aggregation of existing analyses.

This is a deterministic first layer, not a diagnostic model. It reuses structured
outputs from the existing CSV/QC, bioinformatics and patient-journey checks. It does
not read raw patient records, sequence payloads, free-text summaries, or trial data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "0.1.2"
ALLOWED_SOURCES = {"hospital", "laboratory", "bioinformatics", "interoperability"}
ALLOWED_STATUSES = {"pass", "review", "fail", "unknown"}
ALLOWED_SEVERITIES = {"info", "low", "medium", "high", "critical"}
ALLOWED_JOURNEY_CHECKS = {
    "missing_lab_result", "patient_match_conflict", "missing_source_record",
    "timestamp_order_conflict", "organisation_scope_mismatch", "duplicate_record",
    "unlinked_bioinformatics_result", "source_data_incomplete",
}


def _bounded_int(value: Any, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(parsed, maximum))


def _status(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    aliases = {"pass": "pass", "passed": "pass", "ok": "pass",
               "warn": "review", "warning": "review", "review": "review",
               "fail": "fail", "failed": "fail", "unknown": "unknown"}
    return aliases.get(candidate, "unknown")


def _severity(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in ALLOWED_SEVERITIES else "medium"


def _finding(finding_id: str, source: str, rule_id: str, severity: str,
             status: str, evidence: Mapping[str, Any], action: str) -> dict[str, Any]:
    # Return only bounded structured metadata, never arbitrary source text.
    return {
        "finding_id": finding_id,
        "source": source,
        "rule_id": rule_id,
        "severity": severity,
        "status": status,
        "evidence": dict(evidence),
        "requires_human_review": status in {"review", "fail", "unknown"} or severity in {"high", "critical"},
        "recommended_next_step": action,
    }


def build_intelligence_summary(
    *,
    csv_analysis: Mapping[str, Any] | None = None,
    bioinformatics: Mapping[str, Any] | None = None,
    journey_checks: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate existing JLIGHT outputs into a traceable, privacy-minimised summary.

    Inputs must be already-computed structured results, not raw patient records.
    Unknown or malformed fields are treated conservatively. Free-text summaries,
    names, MRNs, filenames, raw sequences and Clinical Trials data are ignored.
    """
    findings: list[dict[str, Any]] = []

    if csv_analysis is not None:
        raw_severity = str(csv_analysis.get("severity", "")).strip().lower()
        risk_score = _bounded_int(csv_analysis.get("riskScore"), maximum=100)
        ml = csv_analysis.get("ml")
        ml = ml if isinstance(ml, Mapping) else {}
        anomaly_count = _bounded_int(ml.get("anomaly_count"))
        westgard = ml.get("westgard_violations")
        westgard_count = len(westgard) if isinstance(westgard, (list, tuple)) else 0

        if raw_severity in {"crit", "critical"} or risk_score >= 70:
            status, severity = "review", "high"
        elif raw_severity in {"att", "attention"} or anomaly_count or westgard_count:
            status, severity = "review", "medium"
        elif raw_severity in {"stab", "stable", "pass"}:
            status, severity = "pass", "info"
        else:
            status, severity = "unknown", "medium"

        findings.append(_finding(
            finding_id="csv_qc_001", source="laboratory",
            rule_id="existing_csv_qc_analysis", severity=severity, status=status,
            evidence={"risk_score": risk_score, "anomaly_count": anomaly_count,
                      "westgard_violation_count": _bounded_int(westgard_count)},
            action="Review the source QC report and confirm flagged issues with an authorised laboratory professional."
            if status != "pass" else
            "Retain the QC report and continue the approved quality-monitoring process.",
        ))

    if bioinformatics is not None:
        qc = _status(bioinformatics.get("qc_status"))
        flags = bioinformatics.get("flags")
        flag_count = len(flags) if isinstance(flags, (list, tuple)) else _bounded_int(bioinformatics.get("flag_count"))
        if qc == "fail":
            severity, status = "high", "review"
        elif qc == "review" or flag_count:
            severity, status = "medium", "review"
        elif qc == "pass":
            severity, status = "info", "pass"
        else:
            severity, status = "medium", "unknown"

        findings.append(_finding(
            finding_id="bio_qc_001", source="bioinformatics",
            rule_id="existing_bioinformatics_qc", severity=severity, status=status,
            evidence={"qc_status": qc, "flag_count": _bounded_int(flag_count)},
            action="Review validated bioinformatics QC output and pipeline provenance before interpreting downstream findings."
            if status != "pass" else
            "Retain QC output and pipeline provenance; a QC pass is not clinical validation.",
        ))

    for item in journey_checks or ():
        if not isinstance(item, Mapping):
            continue
        check_id = str(item.get("check_id", "")).strip().lower()
        source = str(item.get("source", "")).strip().lower()
        if check_id not in ALLOWED_JOURNEY_CHECKS or source not in ALLOWED_SOURCES:
            continue
        status = _status(item.get("status"))
        severity = _severity(item.get("severity"))
        evidence_count = _bounded_int(item.get("evidence_count"))
        findings.append(_finding(
            finding_id=f"journey_{check_id}", source=source, rule_id=check_id,
            severity=severity, status=status, evidence={"evidence_count": evidence_count},
            action="Review the cited source records and resolve or document the discrepancy."
            if status in {"review", "fail", "unknown"} or severity in {"high", "critical"}
            else "Retain source traceability; this check did not flag an issue.",
        ))

    counts = {key: 0 for key in ("pass", "review", "fail", "unknown")}
    for finding in findings:
        counts[finding["status"]] += 1

    # A finding can have status="pass" but still carry high/critical severity.
    # Aggregate the actual per-finding review requirement, not status labels alone.
    review_required = any(item["requires_human_review"] for item in findings)
    overall = ("insufficient_input" if not findings else
               "review_required" if review_required else "no_flags_from_supplied_checks")
    return {
        "engine": "JLIGHT Intelligence Engine",
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "finding_count": len(findings),
        "status_counts": counts,
        "human_review_required": review_required,
        "findings": findings,
        "limitations": [
            "This summary aggregates supplied structured outputs; it does not independently validate source systems.",
            "A flag is a review prompt, not proof of contamination, error, disease or treatment resistance.",
            "Missing inputs mean unknown, not normal or negative.",
            "No direct patient identifiers, raw sequences, free-text source summaries or Clinical Trials data are included.",
        ],
    }


# Clinical Trials has a deliberately separate allow-list and summary builder.
ALLOWED_CLINICAL_TRIAL_CHECKS = {
    "overdue_visit", "protocol_deviation", "incomplete_trial_record",
    "consent_record_incomplete", "adverse_event_followup", "retention_risk",
}


def build_clinical_trials_intelligence_summary(
    *, clinical_trials_checks: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate bounded, de-identified trial workflow checks only.

    No participant identifiers, consent text, adverse-event narratives, medical
    details, or general patient-journey data are accepted or returned.
    """
    findings: list[dict[str, Any]] = []
    for item in clinical_trials_checks or ():
        if not isinstance(item, Mapping):
            continue
        check_id = str(item.get("check_id", "")).strip().lower()
        if check_id not in ALLOWED_CLINICAL_TRIAL_CHECKS:
            continue
        status = _status(item.get("status"))
        severity = _severity(item.get("severity"))
        evidence_count = _bounded_int(item.get("evidence_count"))
        findings.append(_finding(
            finding_id=f"trial_{check_id}",
            source="clinical_trials",
            rule_id=check_id,
            severity=severity,
            status=status,
            evidence={"evidence_count": evidence_count},
            action=(
                "Review the relevant study records with the authorised investigator or study team; JC does not make clinical or protocol decisions."
                if status in {"review", "fail", "unknown"} or severity in {"high", "critical"}
                else "Retain the study record and continue the approved oversight process."
            ),
        ))

    counts = {key: 0 for key in ("pass", "review", "fail", "unknown")}
    for finding in findings:
        counts[finding["status"]] += 1
    review_required = any(item["requires_human_review"] for item in findings)
    overall = (
        "insufficient_input" if not findings else
        "review_required" if review_required else
        "no_flags_from_supplied_checks"
    )
    return {
        "engine": "JLIGHT Clinical Trials Intelligence",
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "finding_count": len(findings),
        "status_counts": counts,
        "human_review_required": review_required,
        "findings": findings,
        "limitations": [
            "This is an aggregate workflow review, not clinical, safety, eligibility or protocol adjudication.",
            "Only allow-listed trial check identifiers, statuses, severity and bounded counts are evaluated.",
            "No participant identifiers, consent text, adverse-event narratives or medical details are included.",
            "Missing inputs mean unknown, not normal or complete.",
        ],
    }
