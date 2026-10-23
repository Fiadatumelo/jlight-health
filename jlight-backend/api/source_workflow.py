"""Authenticated, tenant-scoped API for JLIGHT source-workflow evidence.

Authentication is delegated to Supabase Auth (JWKS or legacy JWT secret).
Organization selection is accepted only when an active membership is confirmed in PostgreSQL.
No patient identity supplied by a source payload is trusted as a verified JLIGHT link.
"""
from __future__ import annotations

import os
import hashlib
import hmac
from datetime import datetime, timezone
from contextlib import contextmanager
from functools import wraps
from uuid import UUID, uuid4

import jwt
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, current_app, g, jsonify, request

from engine.domain_persistence import persist_source_record, persist_workflow_event
from engine.workflow_traceability import normalize_workflow_event, build_workflow_timelines, build_patient_journeys
from engine.source_adapters import parse_source_export
from engine.decision_cards import build_decision_cards
from engine.ingestion_queue import enqueue_export, claim_exports, finish_export

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




VALID_DOMAINS = {"hospital", "laboratory", "bioinformatics", "clinical_trials"}


def _domain_permission(domain: str, action: str = "read") -> bool:
    """Fail-closed check against explicit per-membership domain grants."""
    if domain not in VALID_DOMAINS or action not in {"read", "write", "report"}:
        return False
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute("SELECT set_config('jlight.auth_subject', %s, true)",
                            (g.jlight_actor["subject"],))
                column = {"read": "can_read", "write": "can_write", "report": "can_report"}[action]
                cur.execute(
                    f"""SELECT {column} AS allowed
                        FROM jlight_membership_domain_permissions
                        WHERE organization_id = %s AND auth_subject = %s AND domain = %s""",
                    (g.jlight_actor["organization_id"], g.jlight_actor["subject"], domain),
                )
                row = cur.fetchone()
                return bool(row and row["allowed"])
    except Exception:
        current_app.logger.exception("JLIGHT domain permission check failed")
        return False


def require_domain_scope(action: str = "read"):
    """Require explicit permission for the selected workspace domain."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            domain = request.headers.get("X-JLIGHT-Domain", "").strip().lower()
            if domain not in VALID_DOMAINS:
                return _error("A valid X-JLIGHT-Domain is required", 400)
            if not _domain_permission(domain, action):
                return _error("Access to this domain is not authorised", 403)
            g.jlight_domain = domain
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def require_patient_journey_report(fn):
    """Cross-domain aggregation requires a separate explicit report grant."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        # A comprehensive patient-journey report requires explicit report grants
        # for every included operational domain. Clinical Trials remains separate.
        allowed = all(_domain_permission(domain, "report")
                      for domain in ("hospital", "laboratory", "bioinformatics"))
        if not allowed:
            return _error("Patient-journey reporting is not authorised", 403)
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




def _source_patient_hash(source_system: str, source_patient_ref: str) -> str:
    secret = os.environ.get("JLIGHT_LINKING_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JLIGHT_LINKING_SECRET must contain at least 32 characters")
    canonical = source_system.strip() + "\x1f" + source_patient_ref.strip()
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _lookup_patient_link(conn, organization_id: str, source_system: str, source_hash: str):
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (organization_id,))
        cur.execute(
            """SELECT action, jlight_patient_id FROM jlight_patient_link_events
               WHERE organization_id = %s AND source_system = %s AND source_patient_ref_hash = %s
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (organization_id, source_system, source_hash),
        )
        return cur.fetchone()

@source_workflow_bp.post("/connectors/ingest")
@require_membership
@require_domain_scope("write")
def ingest_source_export():
    """Ingest a read-only FHIR Bundle, HL7 v2 status message, or mapped CSV export."""
    if request.content_length is not None and request.content_length > 2 * 1024 * 1024:
        return _error("Source export exceeds the 2 MB request limit", 413)
    if not request.is_json:
        return _error("JSON object required", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("JSON object required", 400)
    source_system = str(body.get("source_system") or "").strip()
    domain = str(body.get("domain") or "").strip().lower()
    if not source_system:
        return _error("source_system is required", 400)
    if domain == "clinical_trials":
        return _error("Clinical Trials uses its separate participant workflow", 400)
    if domain not in {"hospital", "laboratory", "bioinformatics"}:
        return _error("domain must be hospital, laboratory, or bioinformatics", 400)
    if domain != g.jlight_domain:
        return _error("Source export domain must match the authorised workspace", 403)
    try:
        events = parse_source_export(
            body.get("format"), body.get("payload"),
            source_system=source_system, domain=domain,
        )
        if not events:
            return _error("No supported source status events were found in the export", 422)
        inserted = 0
        duplicates = 0
        with _db() as conn:
            for event in events:
                source_patient_ref = str(event.pop("source_patient_ref", "") or "").strip()
                source_hash = _source_patient_hash(source_system, source_patient_ref) if source_patient_ref and os.environ.get("JLIGHT_LINKING_SECRET") else None
                event["source_patient_ref_hash"] = source_hash
                event["link_status"] = "unlinked"
                event["jlight_patient_id"] = None
                if source_hash:
                    link = _lookup_patient_link(conn, g.jlight_actor["organization_id"], source_system, source_hash)
                    if link and link["action"] == "link" and link["jlight_patient_id"]:
                        event["link_status"] = "verified"
                        event["jlight_patient_id"] = str(link["jlight_patient_id"])
                result = persist_workflow_event(
                    conn, g.jlight_actor["organization_id"], event, commit=False
                )
                if result["action"] == "insert":
                    inserted += 1
                else:
                    duplicates += 1
        return jsonify({
            "success": True,
            "source_system": source_system,
            "domain": domain,
            "received_events": len(events),
            "inserted_events": inserted,
            "duplicate_events": duplicates,
            "patient_linking": "unlinked_pending_trusted_linking",
            "source_values_modified": False,
            "source_system_remains_authoritative": True,
        }), 201 if inserted else 200
    except RuntimeError as exc:
        return _error(str(exc), 503)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        current_app.logger.exception("Source export ingestion failed")
        return _error("Source export could not be persisted", 500)


@source_workflow_bp.post("/connectors/queue")
@require_membership
@require_domain_scope("write")
def queue_source_export():
    """Durably queue an export for processing/replay; does not contact source systems."""
    if not request.is_json:
        return _error("JSON object required", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("JSON object required", 400)
    domain = str(body.get("domain") or "").strip().lower()
    if domain != g.jlight_domain:
        return _error("Queue domain must match the authorised workspace", 403)
    key = str(request.headers.get("Idempotency-Key") or body.get("idempotency_key") or "").strip()
    try:
        with _db() as conn:
            result = enqueue_export(
                conn, g.jlight_actor["organization_id"],
                source_system=body.get("source_system"),
                domain=body.get("domain"),
                export_format=body.get("format"),
                payload=body.get("payload"),
                idempotency_key=key,
            )
        return jsonify({"success": True, **result,
                        "source_system_remains_authoritative": True,
                        "clinical_trials_separate": True}), 202 if result["action"] == "queued" else 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except RuntimeError:
        current_app.logger.exception("Durable queue is not available")
        return _error("Durable ingestion queue is not available", 503)
    except Exception:
        current_app.logger.exception("Source export could not be queued")
        return _error("Source export could not be queued", 500)


@source_workflow_bp.post("/connectors/queue/process")
@require_membership
@require_domain_scope("write")
def process_queued_exports():
    """Process queued exports for the current tenant; retries failures without dropping them."""
    if g.jlight_actor["role"] not in {"owner", "admin"}:
        return _error("Only organization owners or admins can run queue recovery", 403)
    if not request.is_json:
        return _error("JSON object required", 415)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _error("JSON object required", 400)
    try:
        limit = int(body.get("limit", 5))
    except (TypeError, ValueError):
        return _error("limit must be an integer", 400)
    processed, retried, dead_lettered = 0, 0, 0
    try:
        with _db() as conn:
            claimed = claim_exports(conn, g.jlight_actor["organization_id"], limit=limit, domain=g.jlight_domain)
        for item in claimed:
            try:
                events = parse_source_export(
                    item["export_format"], item["payload"],
                    source_system=item["source_system"], domain=item["domain"],
                )
                if not events:
                    raise ValueError("no_supported_status_events")
                with _db() as conn:
                    for event in events:
                        source_ref = str(event.pop("source_patient_ref", "") or "").strip()
                        source_hash = (_source_patient_hash(item["source_system"], source_ref)
                                       if source_ref and os.environ.get("JLIGHT_LINKING_SECRET") else None)
                        event["source_patient_ref_hash"] = source_hash
                        event["link_status"] = "unlinked"
                        event["jlight_patient_id"] = None
                        if source_hash:
                            link = _lookup_patient_link(
                                conn, g.jlight_actor["organization_id"], item["source_system"], source_hash
                            )
                            if link and link["action"] == "link" and link["jlight_patient_id"]:
                                event["link_status"] = "verified"
                                event["jlight_patient_id"] = str(link["jlight_patient_id"])
                        persist_workflow_event(
                            conn, g.jlight_actor["organization_id"], event, commit=False
                        )
                    finish_export(conn, g.jlight_actor["organization_id"], item["id"],
                                  str(item["lease_token"]), success=True)
                processed += 1
            except Exception as exc:
                current_app.logger.warning("Queued export processing failed for queue_id=%s", item["id"])
                try:
                    with _db() as conn:
                        result = finish_export(
                            conn, g.jlight_actor["organization_id"], item["id"],
                            str(item["lease_token"]), success=False,
                            error_code=type(exc).__name__,
                        )
                    if result["status"] == "dead_letter":
                        dead_lettered += 1
                    else:
                        retried += 1
                except Exception:
                    current_app.logger.exception("Queue retry state could not be saved")
                    return _error("A queue item failed and its recovery state could not be saved", 503)
        return jsonify({"success": True, "claimed": len(claimed), "processed": processed,
                        "retried": retried, "dead_lettered": dead_lettered,
                        "source_values_modified": False,
                        "source_system_remains_authoritative": True,
                        "clinical_trials_separate": True})
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        current_app.logger.exception("Queue recovery could not run")
        return _error("Queue recovery could not run", 503)


@source_workflow_bp.post("/patient-keys")
@require_membership
def create_canonical_patient_key():
    """Create a pseudonymous cross-system journey key; no patient identifiers are stored."""
    if g.jlight_actor["role"] not in {"owner", "admin"}:
        return _error("Only organization owners or admins can create patient journey keys", 403)
    key = str(uuid4())
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute(
                    """INSERT INTO jlight_canonical_patients (id, organization_id, created_by)
                       VALUES (%s, %s, %s) RETURNING id, created_at""",
                    (key, g.jlight_actor["organization_id"], g.jlight_actor["subject"]),
                )
                row = cur.fetchone()
        return jsonify({"success": True, "jlight_patient_id": str(row["id"]),
                        "created_at": row["created_at"].isoformat(),
                        "privacy": "pseudonymous key only; no source identifier stored"}), 201
    except Exception:
        current_app.logger.exception("Canonical patient key creation failed")
        return _error("Patient journey key could not be created", 500)


@source_workflow_bp.post("/patient-links")
@require_membership
def create_patient_link_event():
    """Append an admin-verified link/unlink event; raw source identifiers are HMACed."""
    if g.jlight_actor["role"] not in {"owner", "admin"}:
        return _error("Only organization owners or admins can verify patient links", 403)
    if not request.is_json:
        return _error("JSON object required", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("JSON object required", 400)
    source_system = str(body.get("source_system") or "").strip()
    source_ref = str(body.get("source_patient_ref") or "").strip()
    action = str(body.get("action") or "link").strip().lower()
    reason = str(body.get("reason") or "").strip()
    if not source_system or not source_ref or not reason:
        return _error("source_system, source_patient_ref and reason are required", 400)
    if action not in {"link", "unlink"}:
        return _error("action must be link or unlink", 400)
    try:
        source_hash = _source_patient_hash(source_system, source_ref)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    patient_id = None
    if action == "link":
        try:
            patient_id = str(UUID(str(body.get("jlight_patient_id") or "")))
        except (ValueError, TypeError, AttributeError):
            return _error("A valid jlight_patient_id UUID is required for a link action", 400)
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                if patient_id:
                    cur.execute(
                        """SELECT id FROM jlight_canonical_patients
                           WHERE organization_id = %s AND id = %s AND active = TRUE""",
                        (g.jlight_actor["organization_id"], patient_id),
                    )
                    if not cur.fetchone():
                        return _error("The patient journey key is not active in this organization", 404)
                cur.execute(
                    """SELECT action, jlight_patient_id FROM jlight_patient_link_events
                       WHERE organization_id = %s AND source_system = %s AND source_patient_ref_hash = %s
                       ORDER BY created_at DESC, id DESC LIMIT 1""",
                    (g.jlight_actor["organization_id"], source_system, source_hash),
                )
                previous = cur.fetchone()
                if previous and previous["action"] == action and str(previous["jlight_patient_id"] or "") == str(patient_id or ""):
                    return jsonify({"success": True, "action": "duplicate_noop",
                                    "source_system": source_system, "patient_link_verified": action == "link"}), 200
                cur.execute(
                    """INSERT INTO jlight_patient_link_events
                       (organization_id, source_system, source_patient_ref_hash, action,
                        jlight_patient_id, reason, verified_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       RETURNING id, created_at""",
                    (g.jlight_actor["organization_id"], source_system, source_hash, action,
                     patient_id, reason, g.jlight_actor["subject"]),
                )
                row = cur.fetchone()
        return jsonify({"success": True, "action": action, "link_event_id": row["id"],
                        "created_at": row["created_at"].isoformat(),
                        "patient_link_verified": action == "link",
                        "source_patient_identifier_stored": False}), 201
    except Exception:
        current_app.logger.exception("Patient link event could not be saved")
        return _error("Patient link event could not be saved", 500)


@source_workflow_bp.get("/patient-keys")
@require_membership
def list_canonical_patient_keys():
    if g.jlight_actor["role"] not in {"owner", "admin", "clinician", "laboratory", "bioinformatics"}:
        return _error("This membership cannot view patient journey keys", 403)
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute(
                    """SELECT id, created_at FROM jlight_canonical_patients
                       WHERE organization_id = %s AND active = TRUE ORDER BY created_at DESC LIMIT 1000""",
                    (g.jlight_actor["organization_id"],),
                )
                rows = cur.fetchall()
        return jsonify({"success": True, "patient_keys": [
            {"jlight_patient_id": str(row["id"]), "created_at": row["created_at"].isoformat()}
            for row in rows
        ]})
    except Exception:
        current_app.logger.exception("Patient journey keys could not be loaded")
        return _error("Patient journey keys could not be loaded", 500)


@source_workflow_bp.get("/patient-journeys")
@require_membership
@require_patient_journey_report
def get_patient_journeys():
    """Return one verified timeline across Hospital, Laboratory and Bioinformatics."""
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
                       WHERE organization_id = %s AND patient_link_verified = TRUE
                       ORDER BY observed_at, event_id LIMIT 10000""",
                    (g.jlight_actor["organization_id"],),
                )
                rows = cur.fetchall()
        events = [{
            "event_id": row["event_id"], "source_system": row["source_system"],
            "source_record_id": row["source_record_id"], "domain": row["domain"],
            "event_type": row["event_type"], "observed_at": row["observed_at"].isoformat(),
            "source_status": row["source_status"], "jlight_patient_id": row["jlight_patient_id"],
            "patient_link_verified": row["patient_link_verified"],
            "source_values_modified": row["source_values_modified"],
        } for row in rows]
        return jsonify({"success": True, **build_patient_journeys(events)})
    except Exception:
        current_app.logger.exception("Cross-domain patient journeys could not be loaded")
        return _error("Patient journeys could not be loaded", 500)


@source_workflow_bp.get("/decision-cards")
@require_membership
@require_domain_scope("read")
def get_decision_cards():
    """Generate traceable operational cards from the tenant's observed source events."""
    try:
        try:
            threshold = int(request.args.get("stall_after_minutes", "120"))
        except ValueError:
            return _error("stall_after_minutes must be an integer", 400)
        if threshold < 1 or threshold > 10080:
            return _error("stall_after_minutes must be between 1 and 10080", 400)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute(
                    """SELECT event_id, source_system, source_record_id, domain, event_type,
                              observed_at, source_status
                       FROM jlight_workflow_events
                       WHERE organization_id = %s AND domain = %s
                       ORDER BY observed_at DESC, event_id LIMIT 5000""",
                    (g.jlight_actor["organization_id"], g.jlight_domain),
                )
                rows = cur.fetchall()
        events = [{
            "event_id": row["event_id"],
            "source_system": row["source_system"],
            "source_record_id": row["source_record_id"],
            "domain": row["domain"],
            "event_type": row["event_type"],
            "observed_at": row["observed_at"].isoformat(),
            "source_status": row["source_status"],
        } for row in rows]
        cards = build_decision_cards(
            events, now=datetime.now(timezone.utc), stall_after_minutes=threshold
        )
        return jsonify({
            "success": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cards": cards,
            "card_count": len(cards),
            "monitoring_window_minutes": threshold,
            "source_values_modified": False,
            "source_system_remains_authoritative": True,
        })
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        current_app.logger.exception("Decision card generation failed")
        return _error("Decision cards could not be generated", 500)


@source_workflow_bp.get("/connector-freshness")
@require_membership
@require_domain_scope("read")
def get_connector_freshness():
    """Report when source feeds last delivered an event; does not probe source systems."""
    try:
        try:
            stale_after = int(request.args.get("stale_after_minutes", "60"))
        except ValueError:
            return _error("stale_after_minutes must be an integer", 400)
        if stale_after < 1 or stale_after > 10080:
            return _error("stale_after_minutes must be between 1 and 10080", 400)
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('jlight.organization_id', %s, true)",
                            (g.jlight_actor["organization_id"],))
                cur.execute(
                    """SELECT source_system, domain, max(observed_at) AS last_observed_at,
                              count(*) AS event_count
                       FROM jlight_workflow_events
                       WHERE organization_id = %s AND domain = %s
                       GROUP BY source_system, domain
                       ORDER BY source_system, domain""",
                    (g.jlight_actor["organization_id"], g.jlight_domain),
                )
                rows = cur.fetchall()
        now = datetime.now(timezone.utc)
        feeds = []
        for row in rows:
            last_seen = row["last_observed_at"]
            age = max(0, int((now - last_seen).total_seconds() // 60))
            feeds.append({
                "source_system": row["source_system"],
                "domain": row["domain"],
                "last_observed_at": last_seen.isoformat(),
                "minutes_since_last_event": age,
                "event_count": row["event_count"],
                "freshness": "stale_or_disconnected" if age >= stale_after else "recent",
                "meaning": "Feed freshness only; this endpoint does not directly probe source-system availability.",
            })
        return jsonify({"success": True, "feeds": feeds, "stale_after_minutes": stale_after})
    except Exception:
        current_app.logger.exception("Connector freshness query failed")
        return _error("Connector freshness could not be loaded", 500)


@source_workflow_bp.get("/workflow-timelines")
@require_membership
@require_domain_scope("read")
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
                       WHERE organization_id = %s AND domain = %s
                       ORDER BY observed_at, event_id LIMIT 5000""",
                    (g.jlight_actor["organization_id"], g.jlight_domain),
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
