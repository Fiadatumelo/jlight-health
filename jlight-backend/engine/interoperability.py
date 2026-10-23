"""JLIGHT interoperability foundation.

Canonicalises supplied records, exposes source freshness, and links only explicitly
verified patient identifiers. This module does not infer identity or diagnose disease.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
