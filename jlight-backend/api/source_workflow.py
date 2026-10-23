"""Authenticated, tenant-scoped API for JLIGHT source-workflow evidence.

Authentication is delegated to Supabase Auth (JWKS or legacy JWT secret).
Organization selection is accepted only when an active membership is confirmed in PostgreSQL.
No patient identity supplied by a source payload is trusted as a verified JLIGHT link.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from uuid import UUID

import jwt
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, current_app, g, jsonify, request

from engine.domain_persistence import persist_source_record, persist_workflow_event
from engine.workflow_traceability import normalize_workflow_event, build_workflow_timelines

source_workflow_bp = Blueprint("source_workflow", __name__, url_prefix="/api")


def _error(message: str, status: int):
    return jsonify({"success": False, "error": message}), status


def _decode_bearer():
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise PermissionError("Bearer access token required")

    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    if not supabase_url and not jwt_secret:
        raise RuntimeError("Authentication is not configured: set SUPABASE_URL or SUPABASE_JWT_SECRET")

    issuer = f"{supabase_url}/auth/v1" if supabase_url else os.environ.get("JLIGHT_JWT_ISSUER")
    try:
        if supabase_url:
            jwks = jwt.PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")
            signing_key = jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, signing_key, algorithms=["RS256", "ES256"],
                audience="authenticated", issuer=issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        else:
            if not issuer:
                raise RuntimeError("JLIGHT_JWT_ISSUER must be configured with SUPABASE_JWT_SECRET")
            claims = jwt.decode(
                token, jwt_secret, algorithms=["HS256"],
                audience="authenticated", issuer=issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        UUID(str(claims["sub"]))
        return claims
    except RuntimeError:
        raise
    except Exception as exc:
        raise PermissionError("Invalid or expired access token") from exc


@contextmanager
def _db():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    try:
        # The login configured in DATABASE_URL must be explicitly granted membership
        # in the non-login jlight_runtime role. This keeps app queries subject to RLS.
        with conn.cursor() as cur:
            cur.execute("SET ROLE jlight_runtime")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def require_membership(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            claims = _decode_bearer()
        except PermissionError as exc:
            return _error(str(exc), 401)
        except RuntimeError:
            current_app.logger.exception("JLIGHT authentication configuration error")
            return _error("Authentication service is not configured", 503)

        requested_org = request.headers.get("X-JLIGHT-Organization", "").strip()
        try:
            org_id = str(UUID(requested_org))
            subject = str(UUID(str(claims["sub"])))
        except (ValueError, TypeError, AttributeError):
            return _error("A valid X-JLIGHT-Organization UUID is required", 400)

        try:
            with _db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('jlight.auth_subject', %s, true)", (subject,))
                    cur.execute(
                        """SELECT organization_id, role FROM jlight_organization_memberships
                           WHERE auth_subject = %s AND organization_id = %s AND active = TRUE""",
                        (subject, org_id),
                    )
                    membership = cur.fetchone()
            if not membership:
                return _error("Active organization membership required", 403)
        except Exception:
            current_app.logger.exception("JLIGHT membership lookup failed")
            return _error("Organization membership could not be verified", 503)

        g.jlight_actor = {"subject": subject, "organization_id": org_id,
                          "role": membership["role"]}
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and g.jlight_actor["role"] == "viewer":
            return _error("This membership is read-only", 403)
        return fn(*args, **kwargs)
    return wrapped


@source_workflow_bp.post("/source-records")
@require_membership
def ingest_source_record():
    """Append an imported source record; source values remain authoritative and unchanged."""
    if not request.is_json:
        return _error("JSON object required", 415)
    record = request.get_json(silent=True)
    if not isinstance(record, dict):
        return _error("JSON object required", 400)
    # Never accept patient linkage as verified from a client/source payload.
    record = dict(record)
    record.pop("jlight_patient_id", None)
    record["link_status"] = "unlinked"
    try:
        with _db() as conn:
            result = persist_source_record(conn, g.jlight_actor["organization_id"], record)
        return jsonify({"success": True, **result}), 201 if result["action"] == "insert" else 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        current_app.logger.exception("Source record ingestion failed")
        return _error("Source record could not be persisted", 500)


@source_workflow_bp.post("/workflow-events")
@require_membership
def ingest_workflow_event():
    """Append one observed workflow event without writing to the source system."""
    if not request.is_json:
        return _error("JSON object required", 415)
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return _error("JSON object required", 400)
    raw = dict(raw)
    raw.pop("jlight_patient_id", None)
    try:
        event = normalize_workflow_event(raw)
        event["link_status"] = "unlinked"
        event["jlight_patient_id"] = None
        with _db() as conn:
            result = persist_workflow_event(conn, g.jlight_actor["organization_id"], event)
        return jsonify({"success": True, **result}), 201 if result["action"] == "insert" else 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        current_app.logger.exception("Workflow event ingestion failed")
        return _error("Workflow event could not be persisted", 500)


@source_workflow_bp.get("/workflow-timelines")
@require_membership
def get_workflow_timelines():
    """Read a tenant's stored source-observed events as a traceability timeline."""
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute(
                    """SELECT event_id, source_system, source_record_id, domain, event_type,
                              observed_at, source_status, jlight_patient_id,
                              patient_link_verified, source_values_modified
                       FROM jlight_workflow_events
                       WHERE organization_id = %s
                       ORDER BY observed_at, event_id LIMIT 5000""",
                    (g.jlight_actor["organization_id"],),
                )
                rows = cur.fetchall()
        events = [{
            "event_id": row["event_id"],
            "source_system": row["source_system"],
            "source_record_id": row["source_record_id"],
            "source_key": f'{row["source_system"]}::{row["source_record_id"]}',
            "domain": row["domain"],
            "event_type": row["event_type"],
            "observed_at": row["observed_at"].isoformat(),
            "source_status": row["source_status"],
            "jlight_patient_id": row["jlight_patient_id"],
            "link_status": "verified" if row["patient_link_verified"] else "unlinked",
            "source_values_modified": row["source_values_modified"],
        } for row in rows]
        return jsonify({"success": True, **build_workflow_timelines(events)})
    except Exception:
        current_app.logger.exception("Workflow timeline query failed")
        return _error("Workflow timelines could not be loaded", 500)
