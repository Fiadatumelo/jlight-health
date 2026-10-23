"""Read-only workflow traceability for records supplied by existing systems.

This module tracks observed status events; it does not register specimens, perform tests,
enter results, control instruments, or mutate source-system workflow state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

SUPPORTED_DOMAINS = {"hospital", "laboratory", "bioinformatics"}
CLINICAL_TRIALS_DOMAIN = "clinical_trials"
ALLOWED_EVENT_TYPES = {
    "order_received",
    "work_started",
    "awaiting_authorisation",
    "authorised",
    "released",
    "cancelled",
    "admission_opened",
    "admission_closed",
    "analysis_started",
    "analysis_completed",
    "quality_review_required",
    "quality_review_completed",
}
TERMINAL_EVENTS = {"released", "cancelled", "admission_closed", "analysis_completed"}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("observed_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_workflow_event(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one status event observed in an existing source system."""
    if not isinstance(raw, Mapping):
        raise ValueError("workflow event must be an object")

    required = (
        "source_system", "source_record_id", "domain", "event_type",
        "observed_at", "event_id",
    )
    missing = [field for field in required if raw.get(field) is None or str(raw.get(field)).strip() == ""]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))

    source_system = str(raw["source_system"]).strip()
    source_record_id = str(raw["source_record_id"]).strip()
    event_id = str(raw["event_id"]).strip()
    domain = str(raw["domain"]).strip().lower()
    event_type = str(raw["event_type"]).strip().lower()

    if domain == CLINICAL_TRIALS_DOMAIN:
        raise ValueError("clinical-trial events belong to the separate participant workflow")
    if domain not in SUPPORTED_DOMAINS:
        raise ValueError(f"unsupported domain: {domain}")
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"unsupported observed event type: {event_type}")

    observed_at = _timestamp(raw["observed_at"])
    patient_id = str(raw.get("jlight_patient_id") or "").strip() or None
    link_status = "verified" if patient_id else "unlinked"

    return {
        "event_id": event_id,
        "source_system": source_system,
        "source_record_id": source_record_id,
        "source_key": f"{source_system}::{source_record_id}",
        "domain": domain,
        "event_type": event_type,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "jlight_patient_id": patient_id,
        "link_status": link_status,
        "source_status": str(raw.get("source_status") or "").strip() or None,
        "source_values_modified": False,
        "read_only_observation": True,
    }


def build_workflow_timelines(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build auditable, read-only timelines without inferring missing events or identity."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    unlinked_event_ids: list[str] = []
    duplicate_event_ids: list[str] = []
    seen: set[str] = set()

    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("normalized event is missing event_id")
        if event_id in seen:
            duplicate_event_ids.append(event_id)
            continue
        seen.add(event_id)

        source_key = str(event.get("source_key") or "").strip()
        if not source_key:
            raise ValueError(f"event {event_id} is missing source_key")
        by_source.setdefault(source_key, []).append(dict(event))
        if event.get("link_status") != "verified" or not event.get("jlight_patient_id"):
            unlinked_event_ids.append(event_id)

    timelines = []
    for source_key, items in sorted(by_source.items()):
        ordered = sorted(items, key=lambda item: (item.get("observed_at", ""), item.get("event_id", "")))
        timelines.append({
            "source_key": source_key,
            "domain": ordered[0].get("domain"),
            "events": ordered,
            "first_observed_at": ordered[0].get("observed_at"),
            "last_observed_at": ordered[-1].get("observed_at"),
            "latest_event_type": ordered[-1].get("event_type"),
            "terminal_event_observed": ordered[-1].get("event_type") in TERMINAL_EVENTS,
            "patient_link_status": (
                "verified" if all(
                    item.get("link_status") == "verified"
                    and item.get("jlight_patient_id") == ordered[0].get("jlight_patient_id")
                    for item in ordered
                ) else "unlinked_or_inconsistent"
            ),
            "source_values_modified": False,
        })

    return {
        "timelines": timelines,
        "unlinked_event_ids": sorted(unlinked_event_ids),
        "duplicate_event_ids": sorted(set(duplicate_event_ids)),
        "read_only_observations": True,
        "source_system_remains_authoritative": True,
    }
