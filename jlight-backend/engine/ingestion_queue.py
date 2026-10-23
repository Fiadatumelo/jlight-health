"""Durable, tenant-scoped queue primitives for retryable source-export ingestion.

Queue entries contain source exports and therefore must be handled as sensitive data.
This module never calls or writes back to source systems. A worker must authenticate the
tenant before invoking these functions and must use the returned lease token to acknowledge.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

SUPPORTED_DOMAINS = {"hospital", "laboratory", "bioinformatics"}


def _org(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("organization_id must be a UUID") from exc


def enqueue_export(connection: Any, organization_id: str, *, source_system: str,
                   domain: str, export_format: str, payload: Any,
                   idempotency_key: str) -> dict[str, Any]:
    """Persist an export once; the same idempotency key cannot enqueue changed content."""
    org_id = _org(organization_id)
    source_system = str(source_system or "").strip()
    domain = str(domain or "").strip().lower()
    export_format = str(export_format or "").strip().lower()
    key = str(idempotency_key or "").strip()
    if not source_system or not key:
        raise ValueError("source_system and idempotency_key are required")
    if domain not in SUPPORTED_DOMAINS:
        raise ValueError("unsupported domain; clinical trials use a separate workflow")
    if export_format not in {"fhir", "hl7v2", "csv"}:
        raise ValueError("unsupported export format")
    if payload is None:
        raise ValueError("payload is required")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
        cur.execute(
            """INSERT INTO jlight_ingestion_queue
               (organization_id, idempotency_key, source_system, domain, export_format, payload)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (organization_id, idempotency_key) DO NOTHING
               RETURNING id, status""",
            (org_id, key, source_system, domain, export_format, serialized),
        )
        row = cur.fetchone()
        if row:
            connection.commit()
            return {"action": "queued", "queue_id": row[0], "status": row[1]}
        cur.execute(
            """SELECT id, status, source_system, domain, export_format, payload
               FROM jlight_ingestion_queue
               WHERE organization_id = %s AND idempotency_key = %s""",
            (org_id, key),
        )
        existing = cur.fetchone()
    if not existing:
        connection.rollback()
        raise RuntimeError("queue idempotency record could not be read")
    # tuple layout is stable with the queue table's selected columns.
    same = (existing[2] == source_system and existing[3] == domain and
            existing[4] == export_format and existing[5] == json.loads(serialized))
    if not same:
        connection.rollback()
        raise ValueError("idempotency_key already exists for a different export; manual review required")
    connection.commit()
    return {"action": "duplicate_noop", "queue_id": existing[0], "status": existing[1]}


def claim_exports(connection: Any, organization_id: str, *, limit: int = 10,
                  lease_seconds: int = 120) -> list[dict[str, Any]]:
    """Atomically lease pending or retryable exports; safe for concurrent workers."""
    org_id = _org(organization_id)
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 10 and 3600")
    token = str(uuid4())
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
        cur.execute(
            """WITH candidates AS (
                 SELECT id FROM jlight_ingestion_queue
                 WHERE organization_id = %s AND attempts < max_attempts
                   AND (status IN ('pending', 'retry') OR
                        (status = 'processing' AND lease_expires_at < now()))
                   AND available_at <= now()
                 ORDER BY created_at, id
                 FOR UPDATE SKIP LOCKED LIMIT %s
               )
               UPDATE jlight_ingestion_queue q
               SET status = 'processing', lease_token = %s,
                   lease_expires_at = now() + (%s * interval '1 second'),
                   attempts = attempts + 1, updated_at = now()
               FROM candidates c WHERE q.id = c.id
               RETURNING q.id, q.idempotency_key, q.source_system, q.domain,
                         q.export_format, q.payload, q.attempts, q.max_attempts,
                         q.lease_token""",
            (org_id, limit, token, lease_seconds),
        )
        rows = cur.fetchall()
    connection.commit()
    return [dict(id=r[0], idempotency_key=r[1], source_system=r[2], domain=r[3],
                 export_format=r[4], payload=r[5], attempts=r[6], max_attempts=r[7],
                 lease_token=r[8]) for r in rows]


def finish_export(connection: Any, organization_id: str, queue_id: int, lease_token: str,
                  *, success: bool, error_code: str | None = None,
                  retry_delay_seconds: int = 60) -> dict[str, Any]:
    """Acknowledge a leased item or schedule bounded retry/dead-letter without losing evidence."""
    org_id = _org(organization_id)
    if not isinstance(queue_id, int) or queue_id < 1:
        raise ValueError("queue_id must be a positive integer")
    if not lease_token:
        raise ValueError("lease_token is required")
    if not isinstance(retry_delay_seconds, int) or not 1 <= retry_delay_seconds <= 86400:
        raise ValueError("retry_delay_seconds must be between 1 and 86400")
    status = "completed" if success else None
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
        cur.execute(
            """UPDATE jlight_ingestion_queue
               SET status = CASE WHEN %s THEN 'completed'
                                 WHEN attempts >= max_attempts THEN 'dead_letter'
                                 ELSE 'retry' END,
                   last_error_code = CASE WHEN %s THEN NULL ELSE %s END,
                   available_at = CASE WHEN %s OR attempts >= max_attempts THEN available_at
                                       ELSE now() + (%s * interval '1 second') END,
                   lease_token = NULL, lease_expires_at = NULL, updated_at = now(),
                   completed_at = CASE WHEN %s THEN now() ELSE completed_at END
               WHERE organization_id = %s AND id = %s AND status = 'processing'
                 AND lease_token = %s
               RETURNING status, attempts, max_attempts""",
            (bool(success), bool(success), (str(error_code or "ingestion_failed")[:80]),
             bool(success), retry_delay_seconds, bool(success), org_id, queue_id, lease_token),
        )
        row = cur.fetchone()
    if not row:
        connection.rollback()
        raise ValueError("queue lease is missing, expired, or no longer owned by this worker")
    connection.commit()
    return {"status": row[0], "attempts": row[1], "max_attempts": row[2]}
