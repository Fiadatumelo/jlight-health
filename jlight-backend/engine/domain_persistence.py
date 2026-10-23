"""Tenant-scoped persistence helpers for JLIGHT's imported source records.

Callers must authenticate the actor and verify organization membership before calling.
The organization ID must come from trusted server-side auth context, never request JSON.
Clinical Trials are intentionally excluded and use a separate workflow.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping
from uuid import UUID

SOURCE_DOMAINS = {"hospital", "laboratory", "bioinformatics"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _organization_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("trusted organization_id must be a UUID") from exc


def payload_digest(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def persist_source_record(connection: Any, organization_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Append an immutable version; exact repeats are idempotent, same-time differences are held."""
    org_id = _organization_id(organization_id)
    if not isinstance(record, Mapping):
        raise ValueError("record must be an object")
    domain = str(record.get("domain") or "").strip().lower()
    if domain not in SOURCE_DOMAINS:
        raise ValueError("unsupported domain; clinical trials must use the separate workflow")
    source_system = str(record.get("source_system") or "").strip()
    source_record_id = str(record.get("source_record_id") or "").strip()
    record_type = str(record.get("record_type") or "").strip()
    source_updated_at = record.get("source_updated_at")
    payload = record.get("data")
    if not source_system or not source_record_id or not record_type or not source_updated_at:
        raise ValueError("source_system, source_record_id, record_type and source_updated_at are required")
    if not isinstance(payload, Mapping):
        raise ValueError("record data must be an object")

    verified = record.get("link_status") == "verified" and bool(record.get("jlight_patient_id"))
    patient_id = str(record["jlight_patient_id"]).strip() if verified else None
    digest = payload_digest(payload)
    source_key = f"{source_system}::{source_record_id}"

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
            cur.execute(
                """SELECT payload_sha256 FROM jlight_source_record_versions
                   WHERE organization_id = %s AND source_system = %s
                     AND source_record_id = %s AND source_updated_at = %s""",
                (org_id, source_system, source_record_id, source_updated_at),
            )
            same_timestamp = cur.fetchall()
            if any(row["payload_sha256"] == digest if isinstance(row, dict) else row[0] == digest for row in same_timestamp):
                connection.commit()
                return {"action": "duplicate_noop", "source_key": source_key, "payload_sha256": digest}
            conflict = bool(same_timestamp)
            link_status = "conflict_hold" if conflict else ("verified" if verified else "unlinked")
            if conflict:
                patient_id = None
                verified = False
            cur.execute(
                """INSERT INTO jlight_source_record_versions
                   (organization_id, source_system, source_record_id, domain, record_type,
                    source_updated_at, payload, payload_sha256, jlight_patient_id,
                    patient_link_verified, link_status, source_values_modified)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, FALSE)
                   ON CONFLICT (organization_id, source_system, source_record_id,
                                source_updated_at, payload_sha256) DO NOTHING
                   RETURNING id""",
                (org_id, source_system, source_record_id, domain, record_type,
                 source_updated_at, json.dumps(payload, ensure_ascii=False, allow_nan=False),
                 digest, patient_id, verified, link_status),
            )
            inserted = cur.fetchone()
        connection.commit()
        return {
            "action": "conflict_hold" if conflict else ("insert" if inserted else "duplicate_noop"),
            "source_key": source_key,
            "payload_sha256": digest,
            "requires_review": conflict,
        }
    except Exception:
        connection.rollback()
        raise


def persist_workflow_event(connection: Any, organization_id: str, event: Mapping[str, Any], *, commit: bool = True) -> dict[str, Any]:
    """Append one immutable source-observed event; do not write to the source system."""
    org_id = _organization_id(organization_id)
    if not isinstance(event, Mapping):
        raise ValueError("event must be an object")
    domain = str(event.get("domain") or "").strip().lower()
    if domain not in SOURCE_DOMAINS:
        raise ValueError("unsupported domain; clinical trials must use the separate workflow")
    required = ("event_id", "source_system", "source_record_id", "event_type", "observed_at")
    missing = [field for field in required if event.get(field) is None or str(event.get(field)).strip() == ""]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    verified = event.get("link_status") == "verified" and bool(event.get("jlight_patient_id"))
    patient_id = str(event["jlight_patient_id"]).strip() if verified else None
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
            cur.execute(
                """INSERT INTO jlight_workflow_events
                   (organization_id, event_id, source_system, source_record_id, domain,
                    event_type, observed_at, source_status, jlight_patient_id,
                    patient_link_verified, source_values_modified)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                   ON CONFLICT (organization_id, event_id) DO NOTHING
                   RETURNING id""",
                (org_id, str(event["event_id"]).strip(), str(event["source_system"]).strip(),
                 str(event["source_record_id"]).strip(), domain, str(event["event_type"]).strip(),
                 event["observed_at"], event.get("source_status"), patient_id, verified),
            )
            inserted = cur.fetchone()
        if commit:
            connection.commit()
        return {"action": "insert" if inserted else "duplicate_noop", "event_id": str(event["event_id"])}
    except Exception:
        connection.rollback()
        raise
