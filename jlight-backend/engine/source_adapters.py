"""Read-only adapters for source-system exports; never control instruments or mutate sources.

Adapters map workflow status metadata and transient source identity references into JLIGHT
events. The API must HMAC identity references before persistence and must never persist raw
references. Clinical result values are not interpreted or used for sample processing.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from engine.workflow_traceability import normalize_workflow_event


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _status_event(source_system: str, source_record_id: str, domain: str,
                  event_type: str, observed_at: str, event_id: str,
                  source_status: str | None = None) -> dict[str, Any]:
    return normalize_workflow_event({
        "source_system": source_system,
        "source_record_id": source_record_id,
        "domain": domain,
        "event_type": event_type,
        "observed_at": observed_at,
        "event_id": event_id,
        "source_status": source_status,
    })


def parse_fhir_bundle(bundle: Mapping[str, Any], *, source_system: str, domain: str) -> list[dict[str, Any]]:
    """Map FHIR R4 Bundle status metadata into events; no result interpretation."""
    if not isinstance(bundle, Mapping) or bundle.get("resourceType") != "Bundle":
        raise ValueError("FHIR input must be a FHIR R4 Bundle object")
    if not source_system.strip():
        raise ValueError("source_system is required")
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        raise ValueError("FHIR Bundle.entry must be an array")
    status_maps = {
        "Encounter": {
            "planned": "order_received", "arrived": "order_received",
            "in-progress": "work_started", "finished": "admission_closed",
            "cancelled": "cancelled", "entered-in-error": "cancelled",
        },
        "ServiceRequest": {
            "draft": "order_received", "active": "order_received",
            "on-hold": "awaiting_authorisation", "completed": "released",
            "revoked": "cancelled", "cancelled": "cancelled", "entered-in-error": "cancelled",
        },
        "Task": {
            "draft": "order_received", "requested": "order_received", "received": "order_received",
            "accepted": "work_started", "in-progress": "work_started",
            "on-hold": "awaiting_authorisation", "completed": "released",
            "failed": "quality_review_required", "cancelled": "cancelled", "entered-in-error": "cancelled",
        },
        "DiagnosticReport": {
            "registered": "order_received", "partial": "work_started",
            "preliminary": "awaiting_authorisation", "final": "released",
            "amended": "released", "corrected": "released", "cancelled": "cancelled",
            "entered-in-error": "cancelled",
        },
    }
    events = []
    for index, entry in enumerate(entries):
        resource = entry.get("resource") if isinstance(entry, Mapping) else None
        if not isinstance(resource, Mapping):
            continue
        resource_type = str(resource.get("resourceType") or "")
        status = str(resource.get("status") or "").lower()
        event_type = status_maps.get(resource_type, {}).get(status)
        if not event_type:
            continue
        resource_id = str(resource.get("id") or "").strip()
        if not resource_id:
            raise ValueError(f"FHIR {resource_type} resource at entry {index} has no id")
        meta = resource.get("meta") if isinstance(resource.get("meta"), Mapping) else {}
        observed_at = meta.get("lastUpdated") or resource.get("issued") or resource.get("authoredOn")
        if resource_type == "Encounter" and not observed_at:
            period = resource.get("period") if isinstance(resource.get("period"), Mapping) else {}
            observed_at = period.get("end") or period.get("start")
        if not observed_at:
            raise ValueError(f"FHIR {resource_type}/{resource_id} has no usable source timestamp")
        stable_id = _stable_id(source_system, resource_type, resource_id, str(observed_at), status)
        event = _status_event(
            source_system, f"{resource_type}/{resource_id}", domain, event_type,
            str(observed_at), stable_id, status,
        )
        # FHIR resources use subject for clinical records and Task.for for the target patient.
        subject = resource.get("subject") if isinstance(resource.get("subject"), Mapping) else {}
        if not subject and isinstance(resource.get("for"), Mapping):
            subject = resource.get("for")
        event["source_patient_ref"] = str(subject.get("reference") or "").strip() or None
        events.append(event)
    return events


def parse_csv_events(text: str, *, source_system: str, domain: str) -> list[dict[str, Any]]:
    """Parse a CSV status export with explicit JLIGHT mapping column names."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("CSV text is required")
    reader = csv.DictReader(io.StringIO(text))
    required = {"source_record_id", "event_type", "observed_at"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("CSV headers must include source_record_id, event_type, observed_at")
    events = []
    for row_number, row in enumerate(reader, start=2):
        source_record_id = (row.get("source_record_id") or "").strip()
        event_type = (row.get("event_type") or "").strip().lower()
        observed_at = (row.get("observed_at") or "").strip()
        source_status = (row.get("source_status") or "").strip() or None
        if not source_record_id or not event_type or not observed_at:
            raise ValueError(f"CSV row {row_number} is missing a required value")
        supplied_id = (row.get("event_id") or "").strip()
        event_id = supplied_id or _stable_id(source_system, source_record_id, event_type, observed_at)
        event = _status_event(source_system, source_record_id, domain, event_type,
                              observed_at, event_id, source_status)
        event["source_patient_ref"] = (row.get("source_patient_ref") or "").strip() or None
        events.append(event)
    return events


def parse_hl7v2_status(message: str, *, source_system: str, domain: str) -> list[dict[str, Any]]:
    """Map HL7 v2 order/status segments to workflow events, requiring an explicit timezone.

    This adapter reads MSH/ORC/OBR status metadata only. It does not interpret OBX
    clinical values, process samples, or send acknowledgements back to the source.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("HL7 message is required")
    segments = [line.strip().split("|") for line in message.strip().replace("\r", "\n").split("\n") if line.strip()]
    msh = next((segment for segment in segments if segment[0] == "MSH"), None)
    if not msh or len(msh) < 10:
        raise ValueError("HL7 message requires MSH-7 timestamp and MSH-10 control ID")
    timestamp = msh[6].strip()
    control_id = msh[9].strip()
    # HL7 v2 timestamps commonly use YYYYMMDDHHMMSS+ZZZZ. Require an explicit
    # offset because silently assuming a site timezone can corrupt event ordering.
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.\d+)?(Z|[+-]\d{4})", timestamp)
    if not match:
        raise ValueError("HL7 MSH-7 must include a timezone offset for safe normalization")
    try:
        year, month, day, hour, minute, second = map(int, match.groups()[:6])
        offset_text = match.group(7)
        if offset_text == "Z":
            offset = timezone.utc
        else:
            sign = 1 if offset_text[0] == "+" else -1
            offset_minutes = int(offset_text[1:3]) * 60 + int(offset_text[3:5])
            offset = timezone(sign * timedelta(minutes=offset_minutes))
        parsed = datetime(year, month, day, hour, minute, second, tzinfo=offset)
        observed_at = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise ValueError("HL7 MSH-7 must be a valid HL7 timestamp with timezone offset") from exc

    patient_segment = next((segment for segment in segments if segment[0] == "PID"), None)
    patient_ref = ""
    if patient_segment and len(patient_segment) > 3:
        patient_ref = patient_segment[3].split("^", 1)[0].strip()

    events = []
    for index, segment in enumerate(segments):
        if segment[0] not in {"ORC", "OBR"}:
            continue
        if segment[0] == "ORC":
            control = segment[1].strip() if len(segment) > 1 else ""
            status = segment[5].strip() if len(segment) > 5 else ""
            order_id = segment[2].strip() if len(segment) > 2 else ""
            status_map = {"NW": "order_received", "SC": "work_started", "IP": "work_started",
                          "CM": "released", "CA": "cancelled", "DC": "cancelled",
                          "HD": "awaiting_authorisation"}
            event_type = status_map.get(control) or status_map.get(status)
            raw_status = status or control
        else:
            order_id = segment[3].strip() if len(segment) > 3 else ""
            status = segment[25].strip() if len(segment) > 25 else ""
            event_type = {"O": "order_received", "P": "work_started", "F": "released",
                          "C": "cancelled", "X": "cancelled"}.get(status)
            raw_status = status
        if not event_type:
            continue
        if not order_id:
            raise ValueError(f"HL7 {segment[0]} segment {index + 1} has no order identifier")
        event = _status_event(
            source_system, order_id, domain, event_type, observed_at,
            _stable_id(source_system, control_id, str(index), segment[0], order_id, raw_status),
            raw_status,
        )
        event["source_patient_ref"] = patient_ref or None
        events.append(event)
    return events


def parse_source_export(format_name: str, payload: Any, *, source_system: str, domain: str) -> list[dict[str, Any]]:
    fmt = str(format_name or "").strip().lower()
    domain = str(domain or "").strip().lower()
    if domain == "clinical_trials":
        raise ValueError("clinical trials belong to the separate participant workflow")
    if domain not in {"hospital", "laboratory", "bioinformatics"}:
        raise ValueError("domain must be hospital, laboratory, or bioinformatics")
    if fmt == "fhir":
        return parse_fhir_bundle(payload, source_system=source_system, domain=domain)
    if fmt == "csv":
        if not isinstance(payload, str):
            raise ValueError("CSV payload must be text")
        return parse_csv_events(payload, source_system=source_system, domain=domain)
    if fmt in {"hl7", "hl7v2"}:
        if not isinstance(payload, str):
            raise ValueError("HL7 payload must be text")
        return parse_hl7v2_status(payload, source_system=source_system, domain=domain)
    raise ValueError("unsupported format; use fhir, csv, or hl7v2")
