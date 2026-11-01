"""JLIGHT interoperability foundation.

Canonicalises supplied records, exposes source freshness, and links only explicitly
verified patient identifiers. This module does not infer identity or diagnose disease.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Iterable, Mapping

DOMAINS = {"hospital", "laboratory", "bioinformatics", "clinical_trials"}
PATIENT_JOURNEY_DOMAINS = {"hospital", "laboratory", "bioinformatics"}


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_record(
    raw: Mapping[str, Any],
    *,
    now: datetime | None = None,
    stale_after_hours: int = 24,
) -> dict[str, Any]:
    """Validate and normalize one supplied source record without altering source data."""
    if not isinstance(raw, Mapping):
        raise ValueError("record must be an object")
    required = ("source_system", "source_record_id", "domain", "record_type", "source_updated_at", "data")
    missing = [key for key in required if raw.get(key) in (None, "")]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    domain = str(raw["domain"]).strip().lower()
    if domain not in DOMAINS:
        raise ValueError(f"unsupported domain: {domain}")
    if not isinstance(raw["data"], Mapping):
        raise ValueError("data must be an object containing supplied source values")
    if stale_after_hours < 1:
        raise ValueError("stale_after_hours must be at least 1")

    updated_at = _parse_timestamp(raw["source_updated_at"], "source_updated_at")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_hours = max(0.0, (now_utc - updated_at).total_seconds() / 3600)
    patient_id = str(raw.get("jlight_patient_id") or "").strip() or None
    participant_id = str(raw.get("trial_participant_id") or "").strip() or None

    # Clinical trial participant records intentionally never enter the shared patient journey.
    if domain == "clinical_trials":
        patient_id = None
    return {
        "source_system": str(raw["source_system"]).strip(),
        "source_record_id": str(raw["source_record_id"]).strip(),
        "source_key": f"{str(raw['source_system']).strip()}::{str(raw['source_record_id']).strip()}",
        "domain": domain,
        "record_type": str(raw["record_type"]).strip(),
        "source_updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        "data": dict(raw["data"]),
        "jlight_patient_id": patient_id,
        "trial_participant_id": participant_id if domain == "clinical_trials" else None,
        "link_status": (
            "separate_trial_workflow" if domain == "clinical_trials"
            else "verified" if patient_id
            else "unlinked"
        ),
        "freshness": "stale" if age_hours > stale_after_hours else "current",
        "age_hours": round(age_hours, 2),
        "provenance": {
            "source_system": str(raw["source_system"]).strip(),
            "source_record_id": str(raw["source_record_id"]).strip(),
            "source_updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            "ingested_at": now_utc.isoformat().replace("+00:00", "Z"),
            "source_values_modified": False,
        },
    }


def build_patient_journeys(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Group verified non-trial records; never match by name, date of birth, or guesswork."""
    journeys: dict[str, list[dict[str, Any]]] = {}
    unlinked: list[dict[str, Any]] = []
    trial_records: list[dict[str, Any]] = []
    seen_source_keys: set[str] = set()
    duplicate_source_keys: list[str] = []
    for record in records:
        domain = str(record.get("domain", "")).lower()
        source_key = str(record.get("source_key") or "")
        if source_key and source_key in seen_source_keys:
            duplicate_source_keys.append(source_key)
            continue
        if source_key:
            seen_source_keys.add(source_key)
        if domain == "clinical_trials":
            trial_records.append(dict(record))
            continue
        if domain not in PATIENT_JOURNEY_DOMAINS:
            unlinked.append({"record": dict(record), "reason": "unsupported_domain"})
            continue
        patient_id = str(record.get("jlight_patient_id") or "").strip()
        if not patient_id or record.get("link_status") != "verified":
            unlinked.append({"record": dict(record), "reason": "verified_patient_link_required"})
            continue
        journeys.setdefault(patient_id, []).append(dict(record))

    return {
        "journeys": [
            {
                "jlight_patient_id": patient_id,
                "records": sorted(items, key=lambda item: (
                    item.get("source_updated_at", ""), item.get("source_key", "")
                )),
                "domains_present": sorted({item.get("domain", "") for item in items}),
                "cross_section": len({item.get("domain", "") for item in items}) > 1,
            }
            for patient_id, items in sorted(journeys.items())
        ],
        "unlinked_records": unlinked,
        "clinical_trial_records_separate": trial_records,
        "duplicate_source_keys": sorted(set(duplicate_source_keys)),
    }


def evaluate_source_health(
    *,
    connection_state: str,
    last_successful_sync_at: str | None,
    now: datetime | None = None,
    stale_after_minutes: int = 60,
) -> dict[str, Any]:
    """Report connection/freshness separately; a stale feed is never labelled healthy."""
    state = str(connection_state or "").strip().lower()
    if state not in {"connected", "degraded", "unavailable"}:
        raise ValueError("connection_state must be connected, degraded, or unavailable")
    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be at least 1")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not last_successful_sync_at:
        return {
            "status": "unavailable" if state == "unavailable" else "not_yet_synced",
            "last_successful_sync_at": None,
            "data_freshness": "unknown",
            "usable_as_current": False,
        }
    synced_at = _parse_timestamp(last_successful_sync_at, "last_successful_sync_at")
    age_minutes = max(0.0, (now_utc - synced_at).total_seconds() / 60)
    fresh = age_minutes <= stale_after_minutes
    if state == "unavailable":
        status = "unavailable"
    elif state == "degraded" or not fresh:
        status = "degraded" if state == "degraded" else "stale"
    else:
        status = "connected"
    return {
        "status": status,
        "last_successful_sync_at": synced_at.isoformat().replace("+00:00", "Z"),
        "data_freshness": "current" if fresh else "stale",
        "age_minutes": round(age_minutes, 2),
        "usable_as_current": status == "connected" and fresh,
    }



def _hl7_timestamp(value: str, field: str) -> datetime:
    """Parse an HL7 TS value only when its timezone offset is explicit."""
    raw = str(value or "").strip()
    match = re.fullmatch(r"(\d{8})(\d{2})?(\d{2})?(\d{2})?(?:\.(\d{1,4}))?([+-]\d{4})", raw)
    if not match:
        raise ValueError(f"{field} must include an explicit HL7 timezone offset")
    date_part, hour, minute, second, fraction, offset = match.groups()
    text = date_part + (hour or "00") + (minute or "00") + (second or "00")
    parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
    sign = 1 if offset[0] == "+" else -1
    offset_minutes = sign * (int(offset[1:3]) * 60 + int(offset[3:5]))
    from datetime import timedelta
    tz = timezone(timedelta(minutes=offset_minutes))
    if fraction:
        parsed = parsed.replace(microsecond=int(fraction.ljust(6, "0")))
    return parsed.replace(tzinfo=tz).astimezone(timezone.utc)


def parse_hl7_v25_message(message: str, *, source_system: str) -> dict[str, Any]:
    """Parse supported HL7 v2.5 ADT/ORM/ORU messages into de-identified intake events.

    This parser does not authenticate a source, persist data, match a patient,
    or establish a live HL7 connection. Patient identifiers are one-way hashed
    for reconciliation; no JLIGHT patient link is asserted by parsing.
    """
    if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > 5_000_000:
        raise ValueError("HL7 message must be non-empty and no larger than 5 MB")
    source = str(source_system or "").strip()
    if not source or len(source) > 128:
        raise ValueError("source_system must be 1–128 characters")
    segments = [line.strip() for line in re.split(r"[\r\n]+", message) if line.strip()]
    if not segments or not segments[0].startswith("MSH"):
        raise ValueError("HL7 message must begin with MSH")
    field_sep = segments[0][3:4]
    if not field_sep or len(segments[0]) < 8:
        raise ValueError("HL7 MSH segment is malformed")
    parsed_segments = []
    for line in segments:
        if len(line) < 3:
            continue
        parsed_segments.append((line[:3], line.split(field_sep)))
    msh = parsed_segments[0][1]
    if len(msh) <= 11 or msh[0] != "MSH":
        raise ValueError("HL7 MSH header is incomplete")
    version = msh[12] if len(msh) > 12 else ""
    if version not in {"2.5", "2.5.1"}:
        raise ValueError("Only HL7 v2.5 and v2.5.1 are supported")
    message_type = msh[9] if len(msh) > 9 else ""
    message_control_id = msh[10] if len(msh) > 10 else ""
    message_time = msh[6] if len(msh) > 6 else ""
    if not message_control_id:
        raise ValueError("HL7 message control ID is required")
    trigger = message_type.split("^", 1)
    code = trigger[0] if trigger else ""
    event_code = trigger[1] if len(trigger) > 1 else ""
    domain_by_type = {
        ("ADT", "A01"): ("hospital", "admission"),
        ("ADT", "A03"): ("hospital", "discharge"),
        ("ADT", "A08"): ("hospital", "patient_update"),
        ("ORM", "O01"): ("laboratory", "laboratory_order"),
        ("ORU", "R01"): ("laboratory", "laboratory_result"),
    }
    if (code, event_code) not in domain_by_type:
        raise ValueError("Unsupported HL7 message type; supported: ADT A01/A03/A08, ORM O01, ORU R01")
    domain, default_event_type = domain_by_type[(code, event_code)]
    pid = next((fields for name, fields in parsed_segments if name == "PID"), None)
    if pid is None or len(pid) <= 3 or not pid[3]:
        raise ValueError("HL7 PID-3 patient identifier is required for reconciliation")
    # PID-3 may contain repeated identifiers. Hash the first identifier plus
    # assigning authority; never return or persist the raw value from this parser.
    identifier_components = pid[3].split("~", 1)[0].split("^")
    raw_identifier = identifier_components[0].strip()
    assigning_authority = identifier_components[3].strip() if len(identifier_components) > 3 else ""
    if not raw_identifier:
        raise ValueError("HL7 PID-3 patient identifier is empty")
    patient_ref_hash = hashlib.sha256(
        (source + "|" + assigning_authority + "|" + raw_identifier).encode("utf-8")
    ).hexdigest()
    fallback_time = _hl7_timestamp(message_time, "MSH-7")
    events: list[dict[str, Any]] = []
    if code == "ADT":
        pv1 = next((fields for name, fields in parsed_segments if name == "PV1"), [])
        event_time = fallback_time
        event_status = {"A01": "admitted", "A03": "discharged", "A08": "updated"}[event_code]
        visit_id = pv1[19] if len(pv1) > 19 and pv1[19] else message_control_id
        events.append({
            "event_id": f"{source}::{message_control_id}::ADT",
            "source_system": source,
            "source_record_id": visit_id,
            "domain": domain,
            "event_type": default_event_type,
            "observed_at": event_time.isoformat().replace("+00:00", "Z"),
            "source_status": event_status,
            "source_patient_ref_hash": patient_ref_hash,
            "jlight_patient_id": None,
            "patient_link_verified": False,
            "source_values_modified": False,
        })
    else:
        order_segments = [fields for name, fields in parsed_segments if name in {"ORC", "OBR"}]
        result_segments = [fields for name, fields in parsed_segments if name == "OBX"]
        if code == "ORM" and not order_segments:
            raise ValueError("HL7 ORM message requires ORC or OBR")
        if code == "ORU" and not result_segments:
            raise ValueError("HL7 ORU message requires at least one OBX result")
        if code == "ORM":
            for index, fields in enumerate(order_segments):
                order_ref = fields[2] if len(fields) > 2 and fields[2] else message_control_id
                status = fields[5] if len(fields) > 5 and fields[5] else "received"
                events.append({
                    "event_id": f"{source}::{message_control_id}::ORM::{index}",
                    "source_system": source,
                    "source_record_id": order_ref,
                    "domain": domain,
                    "event_type": "laboratory_order",
                    "observed_at": fallback_time.isoformat().replace("+00:00", "Z"),
                    "source_status": status,
                    "source_patient_ref_hash": patient_ref_hash,
                    "jlight_patient_id": None,
                    "patient_link_verified": False,
                    "source_values_modified": False,
                })
        else:
            for index, fields in enumerate(result_segments):
                result_time = _hl7_timestamp(fields[14], f"OBX-{index + 1}-14") if len(fields) > 14 and fields[14] else fallback_time
                observation_code = fields[3] if len(fields) > 3 and fields[3] else "unknown_observation"
                result_status = fields[11] if len(fields) > 11 and fields[11] else "unknown"
                events.append({
                    "event_id": f"{source}::{message_control_id}::ORU::{index}",
                    "source_system": source,
                    "source_record_id": f"{message_control_id}:{index + 1}:{observation_code}",
                    "domain": domain,
                    "event_type": "laboratory_result",
                    "observed_at": result_time.isoformat().replace("+00:00", "Z"),
                    "source_status": result_status,
                    "source_patient_ref_hash": patient_ref_hash,
                    "jlight_patient_id": None,
                    "patient_link_verified": False,
                    "source_values_modified": False,
                })
    return {
        "message_control_id": message_control_id,
        "hl7_version": version,
        "message_type": message_type,
        "source_system": source,
        "domain": domain,
        "patient_link_status": "unlinked_pending_governed_reconciliation",
        "events": events,
        "raw_patient_identifier_returned": False,
        "raw_message_persisted": False,
    }


def classify_sync_change(existing: Mapping[str, Any] | None, incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a sync item without silently overwriting an existing source record."""
    source_key = str(incoming.get("source_key") or "")
    if not source_key:
        raise ValueError("incoming record must have source_key")
    if existing is None:
        return {"action": "insert", "source_key": source_key, "requires_review": False}
    if str(existing.get("source_key") or "") != source_key:
        raise ValueError("source_key mismatch; records cannot be reconciled")
    if existing == incoming:
        return {"action": "duplicate_noop", "source_key": source_key, "requires_review": False}
    old_time = _parse_timestamp(existing.get("source_updated_at"), "existing.source_updated_at")
    new_time = _parse_timestamp(incoming.get("source_updated_at"), "incoming.source_updated_at")
    if new_time == old_time:
        return {
            "action": "conflict_hold",
            "source_key": source_key,
            "requires_review": True,
            "reason": "different_payload_same_source_timestamp",
        }
    return {
        "action": "version_candidate",
        "source_key": source_key,
        "requires_review": True,
        "reason": "source_record_changed",
        "existing_source_updated_at": old_time.isoformat().replace("+00:00", "Z"),
        "incoming_source_updated_at": new_time.isoformat().replace("+00:00", "Z"),
    }
