"""
JLIGHT v4 — Flask REST API
=============================
Endpoints:
  POST /api/analyse-csv       — CSV/XLSX QC analysis
  GET  /api/health            — System health check
  GET  /api/cards             — Decision cards (from DB or static)
  POST /api/cards/acknowledge — Acknowledge a card
  GET  /api/audit             — Audit log

Author: JLIGHT · Team Fiada Mothapo · Hackathon 2026
"""

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import json
import traceback
import jwt
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_cors import CORS

from engine.csv_engine import analyse_csv
from api.security import verify_access_token

from engine.intelligence_engine import build_intelligence_summary, build_clinical_trials_intelligence_summary
from engine.patient_journey_reconciliation import reconcile_patient_journeys
from agent.jc_agent import (
    JCContext, JCAgent, JCTool, JCError, JCApprovalRequired,
    JCForbidden, JCInvalidRequest,
)
from agent.jc_provider import (
    explain_jlight_evidence, JCProviderUnavailable, JCProviderInvalidResponse,
)


# ─── App Setup ───────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, origins=[
    "https://jlight-health.co.za",
    "https://www.jlight-health.co.za",
    "http://localhost:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5500",  # VS Code Live Server
])

app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload


# ─── Database (optional) ─────────────────────────────────────────────────────

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    DB_URL = os.environ.get("DATABASE_URL", "")
    DB_AVAILABLE = bool(DB_URL)
except ImportError:
    DB_AVAILABLE = False

def get_db():
    """Get or create database connection for this request."""
    if not DB_AVAILABLE:
        return None
    if "db" not in g:
        try:
            g.db = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        except Exception:
            return None
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

def log_audit(action: str, role: str = "", details: dict = None):
    """Write to audit_log table if DB available, otherwise silent."""
    db = get_db()
    if not db:
        return
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (action, role, details, timestamp) VALUES (%s, %s, %s, %s)",
                (action, role, json.dumps(details or {}), datetime.now(timezone.utc))
            )
        db.commit()
    except Exception:
        pass


# ─── Error Handlers ──────────────────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "detail": str(e)}), 400

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large", "detail": "Maximum 50MB"}), 413

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ─── Helpers ─────────────────────────────────────────────────────────────────

def success(data: dict, status: int = 200):
    return jsonify({"success": True, **data}), status

def error(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status

def get_json_field(data: dict, field: str, required: bool = True):
    val = data.get(field)
    if required and (val is None or val == ""):
        raise ValueError(f"Missing required field: {field}")
    return val


# ─── Bearer-token authentication ──────────────────────────────────────────────
def require_auth(view):
    """Require a verified bearer token on routes that expose protected data."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            return error("Authentication required", 401)
        try:
            claims = verify_access_token(token.strip())
        except jwt.InvalidTokenError:
            return error("Invalid or expired access token", 401)
        except Exception:
            app.logger.warning("Access token verification failed", exc_info=True)
            return error("Authentication verification unavailable", 503)
        if not isinstance(claims, dict) or not claims.get("sub") or claims.get("aud") != "authenticated":
            return error("Authentication required", 401)
        g.auth_claims = claims
        return view(*args, **kwargs)
    return wrapped


def resolve_verified_workspace_scope(allowed_domains, access="read"):
    """Resolve a selected organisation and workspace from verified memberships.

    X-JLIGHT-Organisation and X-JLIGHT-Workspace are untrusted context selectors,
    never authorization claims. Both are re-checked against current database
    membership, active pathway entitlement and member-level permission.
    """
    claims = getattr(g, "auth_claims", None)
    user_id = claims.get("sub") if isinstance(claims, dict) else None
    if not user_id:
        return None, (jsonify({"success": False, "error": "Verified authentication required"}), 401)
    db = get_db()
    if db is None:
        return None, (jsonify({"success": False, "error": "Organisation authorization service unavailable"}), 503)
    allowed = set(allowed_domains)
    requested = request.headers.get("X-JLIGHT-Workspace", "").strip().lower() or None
    requested_org = request.headers.get("X-JLIGHT-Organisation", "").strip() or None
    if requested and requested not in allowed:
        return None, (jsonify({"success": False, "error": "Requested workspace is not supported by this endpoint"}), 403)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            if requested_org:
                cur.execute(
                    """SELECT o.id::text AS organisation_id
                       FROM public.jl_organisations o
                       WHERE o.id::text = %s
                         AND coalesce(o.active, true) = true
                         AND (
                           EXISTS (
                             SELECT 1 FROM public.jlight_organization_memberships m
                             WHERE m.organization_id=o.id AND m.auth_subject=%s AND m.active=true
                           )
                           OR EXISTS (
                             SELECT 1 FROM public.jl_org_memberships m
                             WHERE m.organisation_id=o.id AND m.user_id=%s AND m.status='active'
                           )
                         )
                       LIMIT 1""",
                    (requested_org, user_id, user_id),
                )
            else:
                cur.execute(
                    """SELECT p.org_id::text AS organisation_id
                       FROM public.jl_user_profiles p
                       JOIN public.jl_organisations o ON o.id = p.org_id
                       WHERE p.user_id = %s
                         AND coalesce(p.active, true) = true
                         AND coalesce(o.active, true) = true
                       LIMIT 1""",
                    (user_id,),
                )
            row = cur.fetchone()
            if not row:
                db.rollback()
                return None, (jsonify({"success": False, "error": "Active organisation membership required"}), 403)
            org_id = row["organisation_id"]

            permitted = []
            for domain in sorted(allowed):
                cur.execute(
                    "SELECT public.jlight_has_domain_permission(%s::uuid, %s, %s) AS allowed",
                    (org_id, domain, access),
                )
                permission_row = cur.fetchone()
                if permission_row and permission_row["allowed"] is True:
                    permitted.append(domain)

            if requested:
                if requested not in permitted:
                    db.rollback()
                    return None, (jsonify({"success": False, "error": "Workspace permission denied"}), 403)
                selected = requested
            elif len(permitted) == 1:
                selected = permitted[0]
            elif len(permitted) > 1:
                db.rollback()
                return None, (jsonify({"success": False, "error": "Select an authorised workspace using X-JLIGHT-Workspace"}), 400)
            else:
                db.rollback()
                return None, (jsonify({"success": False, "error": "No active workspace entitlement and member permission found"}), 403)
        db.rollback()
        return {"organisation_id": org_id, "organisation_type": selected,
                "workspace": selected, "user_id": user_id}, None
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        app.logger.exception("Organisation path authorization failed")
        return None, (jsonify({"success": False, "error": "Organisation authorization service unavailable"}), 503)


def require_domain_auth(allowed_domains, access="read"):
    """Authenticate a request and resolve its current organisation/path permission.

    The selected workspace header is only a context selector. The resolver
    re-checks active organisation membership, pathway entitlement and the
    requested read/write/report permission against PostgreSQL on every call.
    """
    allowed = frozenset(str(domain).strip().lower() for domain in allowed_domains)

    def decorate(view):
        @wraps(view)
        def scoped_view(*args, **kwargs):
            scope, scope_error = resolve_verified_workspace_scope(allowed, access=access)
            if scope_error:
                return scope_error
            g.jlight_scope = scope
            return view(*args, **kwargs)

        # Authentication must run before workspace resolution. Never rely on
        # client-supplied identity, role headers, or stale JWT workspace claims.
        authenticated_view = require_auth(scoped_view)

        @wraps(view)
        def wrapped(*args, **kwargs):
            return authenticated_view(*args, **kwargs)
        return wrapped
    return decorate





# ─── Canonical Patient Registry and Bioinformatics Linking ─────────────────────

@app.route("/api/patients/upsert", methods=["POST"])
@require_auth
def api_patient_upsert():
    """Create/update a canonical patient in the active tenant; return its UUID."""
    claims = getattr(g, "auth_claims", None) or {}
    scope, scope_error = resolve_verified_workspace_scope(
        {"hospital", "laboratory", "bioinformatics"}, access="write"
    )
    if scope_error:
        return scope_error
    data = request.get_json(silent=True) or {}
    mrn = str(data.get("mrn") or "").strip()
    full_name = str(data.get("full_name") or "").strip()
    if not mrn or not full_name:
        return error("MRN and full name are required", 400)
    if len(mrn) > 128 or len(full_name) > 300:
        return error("Patient identifiers exceed the permitted length", 400)
    patient_id = str(data.get("patient_id") or "").strip() or None
    allergies = data.get("allergies") if isinstance(data.get("allergies"), list) else []
    chronic = data.get("chronic_conditions") if isinstance(data.get("chronic_conditions"), list) else []
    db = get_db()
    if db is None:
        return error("Patient registry service unavailable", 503)
    org_id = scope["organisation_id"]
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (claims["sub"],))
            cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
            cur.execute("SELECT set_config('jlight.auth_subject', %s, true)", (claims["sub"],))
            values = (
                mrn, str(data.get("id_number") or "").strip() or None, full_name,
                str(data.get("date_of_birth") or "").strip() or None,
                str(data.get("gender") or "").strip() or None,
                str(data.get("phone") or "").strip() or None,
                str(data.get("address") or "").strip() or None,
                str(data.get("next_of_kin") or "").strip() or None,
                str(data.get("next_of_kin_phone") or "").strip() or None,
                str(data.get("blood_group") or "").strip() or None,
                [str(x).strip() for x in allergies if str(x).strip()][:100],
                [str(x).strip() for x in chronic if str(x).strip()][:100],
            )
            if patient_id:
                cur.execute(
                    """UPDATE public.jl_patients SET mrn=%s,id_number=%s,full_name=%s,
                       date_of_birth=NULLIF(%s,'')::date,gender=%s,phone=%s,address=%s,
                       next_of_kin=%s,next_of_kin_phone=%s,blood_group=%s,allergies=%s,
                       chronic_conditions=%s,updated_at=now()
                       WHERE id=%s::uuid AND org_id=%s::uuid AND coalesce(active,true)=true
                       RETURNING id::text,mrn,full_name""",
                    values + (patient_id, org_id),
                )
                row = cur.fetchone()
                if not row:
                    db.rollback()
                    return error("Canonical patient was not found in this organisation", 404)
            else:
                cur.execute(
                    """INSERT INTO public.jl_patients
                       (org_id,mrn,id_number,full_name,date_of_birth,gender,phone,address,
                        next_of_kin,next_of_kin_phone,blood_group,allergies,chronic_conditions,
                        active,source,created_at,updated_at)
                       VALUES (%s::uuid,%s,%s,%s,NULLIF(%s,'')::date,%s,%s,%s,%s,%s,%s,%s,%s,
                               true,'jlight_patient_registry',now(),now())
                       ON CONFLICT (org_id,mrn) DO UPDATE SET
                         id_number=EXCLUDED.id_number,full_name=EXCLUDED.full_name,
                         date_of_birth=EXCLUDED.date_of_birth,gender=EXCLUDED.gender,
                         phone=EXCLUDED.phone,address=EXCLUDED.address,
                         next_of_kin=EXCLUDED.next_of_kin,next_of_kin_phone=EXCLUDED.next_of_kin_phone,
                         blood_group=EXCLUDED.blood_group,allergies=EXCLUDED.allergies,
                         chronic_conditions=EXCLUDED.chronic_conditions,active=true,updated_at=now()
                       RETURNING id::text,mrn,full_name""",
                    (org_id,) + values,
                )
                row = cur.fetchone()
            db.commit()
            return success({"patient": dict(row), "canonical_patient_id": row["id"]})
    except Exception:
        db.rollback()
        app.logger.exception("Canonical patient upsert failed")
        return error("Patient could not be saved to the authorised registry", 503)


@app.route("/api/bioinformatics/runs/upsert", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_bioinformatics_run_upsert():
    """Persist an imported run and optionally link it to one exact canonical patient UUID."""
    data = request.get_json(silent=True) or {}
    run_id = str(data.get("run_id") or "").strip()
    analysis_type = str(data.get("analysis_type") or "Bioinformatics").strip()
    if not run_id or len(run_id) > 255 or not analysis_type:
        return error("A valid source run ID and analysis type are required", 400)
    scope = g.jlight_scope
    org_id = scope["organisation_id"]
    patient_id = str(data.get("patient_id") or "").strip() or None
    accession_no = str(data.get("accession_no") or run_id).strip()
    db = get_db()
    if db is None:
        return error("Bioinformatics persistence service unavailable", 503)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (scope["user_id"],))
            cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
            cur.execute("SELECT set_config('jlight.auth_subject', %s, true)", (scope["user_id"],))
            if patient_id:
                cur.execute(
                    """SELECT id FROM public.jl_patients
                       WHERE id=%s::uuid AND org_id=%s::uuid AND coalesce(active,true)=true LIMIT 1""",
                    (patient_id, org_id),
                )
                if not cur.fetchone():
                    db.rollback()
                    return error("Patient UUID is not an active patient in this organisation", 404)
            cur.execute(
                """INSERT INTO public.jl_bio_accessions
                   (org_id,patient_id,accession_no,sample_type,created_at)
                   VALUES (%s::uuid,%s::uuid,%s,%s,now())
                   ON CONFLICT (org_id,accession_no) DO UPDATE SET
                     patient_id=COALESCE(public.jl_bio_accessions.patient_id,EXCLUDED.patient_id)
                   WHERE public.jl_bio_accessions.patient_id IS NULL
                      OR EXCLUDED.patient_id IS NULL
                      OR public.jl_bio_accessions.patient_id=EXCLUDED.patient_id
                   RETURNING id""",
                (org_id, patient_id, accession_no, str(data.get("sample_type") or "Not supplied")),
            )
            accession = cur.fetchone()
            if not accession:
                db.rollback()
                return error("Accession is already linked to a different patient; no changes made", 409)
            cur.execute(
                """INSERT INTO public.jl_bio_runs
                   (org_id,accession_id,patient_id,run_id,analysis_type,platform,
                    reference_genome,pipeline,pipeline_version,operator,stage,submitted_at,
                    completed_at,created_at)
                   VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,now(),
                           CASE WHEN %s='completed' THEN now() ELSE NULL END,now())
                   ON CONFLICT (org_id,run_id) DO UPDATE SET
                     accession_id=EXCLUDED.accession_id,
                     patient_id=COALESCE(EXCLUDED.patient_id,public.jl_bio_runs.patient_id),
                     analysis_type=EXCLUDED.analysis_type,
                     platform=COALESCE(EXCLUDED.platform,public.jl_bio_runs.platform),
                     reference_genome=COALESCE(EXCLUDED.reference_genome,public.jl_bio_runs.reference_genome),
                     pipeline=COALESCE(EXCLUDED.pipeline,public.jl_bio_runs.pipeline),
                     pipeline_version=COALESCE(EXCLUDED.pipeline_version,public.jl_bio_runs.pipeline_version),
                     stage=EXCLUDED.stage,
                     completed_at=COALESCE(EXCLUDED.completed_at,public.jl_bio_runs.completed_at)
                   WHERE public.jl_bio_runs.patient_id IS NULL
                      OR EXCLUDED.patient_id IS NULL
                      OR public.jl_bio_runs.patient_id=EXCLUDED.patient_id
                   RETURNING id::text,run_id,patient_id::text,accession_id::text""",
                (org_id, accession["id"], patient_id, run_id, analysis_type,
                 str(data.get("platform") or "") or None,
                 str(data.get("reference_genome") or "") or None,
                 str(data.get("pipeline") or "TBProfiler"),
                 str(data.get("pipeline_version") or "") or None,
                 str(data.get("operator") or "") or None,
                 str(data.get("stage") or "completed"),
                 str(data.get("stage") or "completed")),
            )
            row = cur.fetchone()
            if not row:
                db.rollback()
                return error("Run is already linked to a different patient; no changes made", 409)
            db.commit()
            return success({"run": dict(row), "canonical_run_id": row["id"],
                            "canonical_accession_id": row["accession_id"]})
    except Exception:
        db.rollback()
        app.logger.exception("Canonical Bioinformatics run upsert failed")
        return error("Bioinformatics run could not be saved to the authorised registry", 503)


# ─── Authoritative Patient Journey ────────────────────────────────────────────

def _patient_journey_authorisation(user_id):
    """Resolve the active organisation and every independently permitted care domain."""
    db = get_db()
    if db is None:
        return None, None, (jsonify({"success": False, "error": "Patient Journey data service unavailable"}), 503)
    requested_org = request.headers.get("X-JLIGHT-Organisation", "").strip() or None
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            if requested_org:
                cur.execute(
                    """SELECT o.id::text AS organisation_id
                       FROM public.jl_organisations o
                       WHERE o.id::text=%s AND coalesce(o.active,true)=true
                         AND (EXISTS (SELECT 1 FROM public.jlight_organization_memberships m
                                      WHERE m.organization_id=o.id AND m.auth_subject=%s AND m.active=true)
                           OR EXISTS (SELECT 1 FROM public.jl_org_memberships m
                                      WHERE m.organisation_id=o.id AND m.user_id=%s AND m.status='active'))
                       LIMIT 1""",
                    (requested_org, user_id, user_id),
                )
            else:
                cur.execute(
                    """SELECT p.org_id::text AS organisation_id
                       FROM public.jl_user_profiles p
                       JOIN public.jl_organisations o ON o.id=p.org_id
                       WHERE p.user_id=%s AND coalesce(p.active,true)=true
                         AND coalesce(o.active,true)=true LIMIT 1""",
                    (user_id,),
                )
            row = cur.fetchone()
            if not row:
                db.rollback()
                return None, None, (jsonify({"success": False, "error": "Active organisation membership required"}), 403)
            org_id = row["organisation_id"]
            permitted = []
            for domain in ("hospital", "laboratory", "bioinformatics"):
                cur.execute(
                    "SELECT public.jlight_has_domain_permission(%s::uuid,%s,'read') AS allowed",
                    (org_id, domain),
                )
                permission = cur.fetchone()
                if permission and permission["allowed"] is True:
                    permitted.append(domain)
        db.rollback()
        if not permitted:
            return None, None, (jsonify({"success": False, "error": "Patient Journey requires at least one authorised care workspace"}), 403)
        return org_id, set(permitted), None
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        app.logger.exception("Patient Journey authorisation failed")
        return None, None, (jsonify({"success": False, "error": "Patient Journey authorisation unavailable"}), 503)


def _journey_event(source, event_type, occurred_at, status, record_id, summary):
    return {
        "source": source,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else (str(occurred_at) if occurred_at else None),
        "status": str(status or "recorded"),
        "source_record_id": str(record_id) if record_id is not None else None,
        "summary": str(summary or ""),
    }


@app.route("/api/patient-journey/<uuid:patient_id>", methods=["GET"])
@require_auth
def api_patient_journey(patient_id):
    """Return a patient timeline from source tables the verified member may read.

    The patient UUID is an exact source-record key, not a demographic match.
    Clinical Trials is deliberately excluded; its participant timeline is separate.
    """
    claims = getattr(g, "auth_claims", None)
    if not isinstance(claims, dict) or not claims.get("sub"):
        return error("Verified authentication required", 401)
    org_id, domains, auth_error = _patient_journey_authorisation(claims["sub"])
    if auth_error:
        return auth_error
    db = get_db()
    if db is None:
        return error("Patient Journey data service unavailable", 503)
    events = []
    journey_records = []
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (claims["sub"],))
            cur.execute("SELECT set_config('jlight.organization_id', %s, true)", (org_id,))
            cur.execute("SELECT set_config('jlight.auth_subject', %s, true)", (claims["sub"],))
            cur.execute(
                """SELECT id FROM public.jl_patients
                   WHERE id=%s::uuid AND org_id=%s::uuid AND coalesce(active,true)=true LIMIT 1""",
                (str(patient_id), org_id),
            )
            if not cur.fetchone():
                db.rollback()
                return error("Patient record not found in this organisation", 404)

            if "hospital" in domains:
                cur.execute(
                    """SELECT id, admitted_at, status, admission_no, source
                       FROM public.jl_admissions
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY admitted_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    events.append(_journey_event("Hospital", "admission", row["admitted_at"], row["status"],
                        row["id"], "Admission record" + ((" · " + row["admission_no"]) if row.get("admission_no") else "") +
                        ((" · source: " + row["source"]) if row.get("source") else "")))

                cur.execute(
                    """SELECT id,test_name,priority,ordered_at,specimen_collected_at,result_received_at,
                              clinical_action_at,tat_hours,tat_target_hours,tat_breached,journey_gap_flag
                       FROM public.jl_clinical_orders
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY ordered_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    action_status = "action_recorded" if row.get("clinical_action_at") else (
                        "action_overdue_review" if row.get("journey_gap_flag") or row.get("tat_breached")
                        else "awaiting_clinical_action" if row.get("result_received_at") else "in_progress"
                    )
                    summary = (row.get("test_name") or "Clinical order")
                    if row.get("priority"):
                        summary += " · priority: " + row["priority"]
                    if row.get("tat_hours") is not None:
                        summary += " · turnaround: " + str(row["tat_hours"]) + " h"
                    if row.get("tat_target_hours") is not None:
                        summary += " · target: " + str(row["tat_target_hours"]) + " h"
                    if row.get("journey_gap_flag"):
                        summary += " · documented journey gap"
                    events.append(_journey_event("Hospital", "clinical_order", row["ordered_at"],
                        "ordered", row["id"], summary))
                    if row.get("specimen_collected_at"):
                        events.append(_journey_event("Hospital", "specimen_collection_recorded",
                            row["specimen_collected_at"], "recorded", row["id"], "Specimen collection timestamp supplied by Hospital"))
                    if row.get("result_received_at"):
                        events.append(_journey_event("Hospital", "result_received_by_hospital",
                            row["result_received_at"], "received", row["id"], "Result receipt recorded by Hospital"))
                    if row.get("clinical_action_at"):
                        events.append(_journey_event("Hospital", "clinical_action_recorded",
                            row["clinical_action_at"], "action_recorded", row["id"], "Clinical action timestamp recorded"))
                    elif row.get("result_received_at"):
                        events.append(_journey_event("Hospital", "clinical_action_pending",
                            row["result_received_at"], action_status, row["id"],
                            "Result receipt is recorded; no clinical action timestamp is present in this source record"))
            
            if "laboratory" in domains:
                cur.execute(
                    """SELECT id, order_number, priority, status, ordered_at, received_at, resulted_at
                       FROM public.jl_lab_orders
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY ordered_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    events.append(_journey_event("Laboratory", "laboratory_order", row["ordered_at"] or row["received_at"],
                        row["status"], row["id"], "Order" + ((" " + row["order_number"]) if row.get("order_number") else "") +
                        ((" · priority: " + row["priority"]) if row.get("priority") else "")))
                cur.execute(
                    """SELECT id, accession_no, sample_type, collected_at, received_at, stage
                       FROM public.jl_lab_samples
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY collected_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    events.append(_journey_event("Laboratory", "specimen_status", row["collected_at"] or row["received_at"],
                        row["stage"], row["id"], "Specimen status" +
                        ((" · accession: " + row["accession_no"]) if row.get("accession_no") else "") +
                        ((" · type: " + row["sample_type"]) if row.get("sample_type") else "")))
                cur.execute(
                    """SELECT id, test_name, result_value, result_text, result_unit, interpretation,
                              is_critical, critical_notified_at, status, resulted_at, verified_at
                       FROM public.jl_lab_results
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY resulted_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    result_value = row.get("result_value")
                    value = str(result_value) if result_value is not None else (row.get("result_text") or "value not supplied")
                    summary = (row.get("test_name") or "Laboratory result") + ": " + value
                    if row.get("result_unit"):
                        summary += " " + row["result_unit"]
                    if row.get("interpretation"):
                        summary += " · interpretation: " + row["interpretation"]
                    if row.get("is_critical"):
                        summary += " · critical result"
                    if row.get("critical_notified_at"):
                        summary += " · notification recorded"
                    events.append(_journey_event("Laboratory", "laboratory_result", row["resulted_at"] or row["verified_at"],
                        row["status"], row["id"], summary))

            if "bioinformatics" in domains:
                cur.execute(
                    """SELECT id,accession_no,sample_type,collection_date,received_at
                       FROM public.jl_bio_accessions
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY received_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    events.append(_journey_event("Bioinformatics", "bioinformatics_accession",
                        row["received_at"] or row["collection_date"], "received" if row.get("received_at") else "collected",
                        row["id"], "Accession" +
                        ((" " + row["accession_no"]) if row.get("accession_no") else "") +
                        ((" · sample type: " + row["sample_type"]) if row.get("sample_type") else "")))
                cur.execute(
                    """SELECT id, run_id, analysis_type, pipeline, pipeline_version, stage,
                              submitted_at, completed_at
                       FROM public.jl_bio_runs
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                       ORDER BY submitted_at DESC NULLS LAST LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                runs = cur.fetchall()
                run_ids = [str(row["id"]) for row in runs]
                for row in runs:
                    events.append(_journey_event("Bioinformatics", "analysis_run", row["completed_at"] or row["submitted_at"],
                        row["stage"], row["id"], (row.get("analysis_type") or "Analysis") +
                        ((" · pipeline: " + row["pipeline"]) if row.get("pipeline") else "") +
                        ((" · version: " + row["pipeline_version"]) if row.get("pipeline_version") else "")))
                if run_ids:
                    cur.execute(
                        """SELECT q.id,q.run_id,q.coverage_mean,q.mapping_rate,q.q_score,q.dup_rate,
                                  q.gc_content,q.contamination,q.qc_status
                           FROM public.jl_bio_qc q
                           JOIN public.jl_bio_runs r ON r.id=q.run_id AND r.org_id=q.org_id
                           WHERE q.org_id=%s::uuid AND r.patient_id=%s::uuid
                           ORDER BY q.created_at DESC LIMIT 500""",
                        (org_id, str(patient_id)),
                    )
                    for row in cur.fetchall():
                        metrics = [("coverage", row.get("coverage_mean")), ("mapping", row.get("mapping_rate")),
                                   ("Q-score", row.get("q_score")), ("duplication", row.get("dup_rate")),
                                   ("GC", row.get("gc_content")), ("contamination", row.get("contamination"))]
                        summary = "Bioinformatics QC" + "".join(" · %s: %s" % (k, v) for k,v in metrics if v is not None)
                        events.append(_journey_event("Bioinformatics", "quality_control", None, row["qc_status"], row["id"], summary))
                    cur.execute(
                        """SELECT a.id,a.run_id,a.gene,a.antibiotic_class,a.resistance_level,a.confidence,a.database_version
                           FROM public.jl_bio_amr a
                           JOIN public.jl_bio_runs r ON r.id=a.run_id AND r.org_id=a.org_id
                           WHERE a.org_id=%s::uuid AND r.patient_id=%s::uuid
                           ORDER BY a.created_at DESC LIMIT 1000""",
                        (org_id, str(patient_id)),
                    )
                    for row in cur.fetchall():
                        summary = (row.get("gene") or "Resistance finding") + " · " + (row.get("antibiotic_class") or "drug class") + \
                            " · " + (row.get("resistance_level") or "source call")
                        if row.get("confidence") is not None:
                            summary += " · confidence: " + str(row["confidence"])
                        if row.get("database_version"):
                            summary += " · database: " + row["database_version"]
                        events.append(_journey_event("Bioinformatics", "resistance_finding", None, row["resistance_level"],
                            row["id"], summary))

            # Build reconciliation evidence from canonical, organisation-scoped
            # source rows. Patient UUID is the exact FK link; no demographic matching.
            if "hospital" in domains:
                cur.execute(
                    """SELECT id, lab_order_id FROM public.jl_clinical_orders
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid
                         AND lab_order_id IS NOT NULL LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    journey_records.append({
                        "domain": "hospital", "source_key": "hospital::clinical_order::" + str(row["id"]),
                        "jlight_patient_id": str(patient_id), "link_status": "verified",
                        "data": {"order_id": str(row.get("lab_order_id")) if row.get("lab_order_id") else None},
                    })

            if "laboratory" in domains:
                cur.execute(
                    """SELECT id FROM public.jl_lab_orders
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    journey_records.append({
                        "domain": "laboratory", "source_key": "laboratory::order::" + str(row["id"]),
                        "jlight_patient_id": str(patient_id), "link_status": "verified",
                        "data": {"order_id": str(row["id"])},
                    })
                cur.execute(
                    """SELECT id, order_id, accession_no FROM public.jl_lab_samples
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    journey_records.append({
                        "domain": "laboratory", "source_key": "laboratory::sample::" + str(row["id"]),
                        "jlight_patient_id": str(patient_id), "link_status": "verified",
                        "data": {
                            "order_id": str(row["order_id"]) if row.get("order_id") else None,
                            "accession_id": row.get("accession_no"),
                        },
                    })

            if "bioinformatics" in domains:
                cur.execute(
                    """SELECT id, accession_no FROM public.jl_bio_accessions
                       WHERE org_id=%s::uuid AND patient_id=%s::uuid LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    journey_records.append({
                        "domain": "bioinformatics", "source_key": "bioinformatics::accession::" + str(row["id"]),
                        "jlight_patient_id": str(patient_id), "link_status": "verified",
                        "data": {"accession_id": row.get("accession_no")},
                    })
                cur.execute(
                    """SELECT r.id, a.accession_no FROM public.jl_bio_runs r
                       LEFT JOIN public.jl_bio_accessions a
                         ON a.id=r.accession_id AND a.org_id=r.org_id
                       WHERE r.org_id=%s::uuid AND r.patient_id=%s::uuid LIMIT 500""",
                    (org_id, str(patient_id)),
                )
                for row in cur.fetchall():
                    journey_records.append({
                        "domain": "bioinformatics", "source_key": "bioinformatics::run::" + str(row["id"]),
                        "jlight_patient_id": str(patient_id), "link_status": "verified",
                        "data": {"accession_id": row.get("accession_no")},
                    })

            # Cross-domain event stream is included only for verified patient links
            # and only when the member has permission for the event's own domain.
            cur.execute(
                """SELECT event_id,domain,event_type,observed_at,source_status,source_record_id
                   FROM public.jlight_workflow_events
                   WHERE organization_id=%s::uuid AND jlight_patient_id=%s AND patient_link_verified=true
                     AND domain = ANY(%s)
                   ORDER BY observed_at DESC NULLS LAST LIMIT 1000""",
                (org_id, str(patient_id), sorted(domains)),
            )
            for row in cur.fetchall():
                events.append(_journey_event(row["domain"].title(), row["event_type"], row["observed_at"],
                    row["source_status"], row["source_record_id"] or row["event_id"], "Verified linked workflow event"))
        db.rollback()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        app.logger.exception("Patient Journey source retrieval failed")
        return error("Patient Journey could not retrieve authorised source events", 503)

    events.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
    reconciliation = None
    if {"hospital", "laboratory", "bioinformatics"}.issubset(domains):
        reconciliation = reconcile_patient_journeys(journey_records)
    return jsonify({
        "success": True,
        "patient_id": str(patient_id),
        "organisation_id": org_id,
        "available_domains": sorted(domains),
        "clinical_trials_included": False,
        "reconciliation": reconciliation,
        "reconciliation_status": "completed" if reconciliation is not None else "not_run_insufficient_workspace_permissions",
        "event_count": len(events),
        "events": events[:3000],
        "limitations": [
            "Only exact patient UUID links in this organisation are included.",
            "Only source domains for which this member has active read permission are included.",
            "Clinical Trials is isolated and must be viewed in its separate participant timeline.",
            "Source systems remain authoritative; missing events are unknown, not proof that an event did not occur."
        ]
    }), 200


# ─── JLIGHT Intelligence / JC ─────────────────────────────────────────────────

def _write_jc_audit(event):
    """Persist metadata-only JC audit events; fail closed if audit storage is unavailable."""
    db = get_db()
    if db is None:
        raise RuntimeError("Audit storage unavailable")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (action, role, details, timestamp) VALUES (%s, %s, %s, %s)",
            (
                "jc_" + str(event.get("outcome", "unknown")),
                "JC",
                json.dumps({
                    "agent": "JC",
                    "tool": event.get("tool"),
                    "outcome": event.get("outcome"),
                    "reason": event.get("reason"),
                    "user_id": event.get("user_id"),
                    "organisation_id": event.get("organisation_id"),
                }),
                datetime.now(timezone.utc),
            ),
        )
    db.commit()


@app.route("/api/intelligence/summary", methods=["POST"])
@require_auth
def api_intelligence_summary():
    """Run deterministic intelligence aggregation under verified tenant scope."""
    claims = getattr(g, "auth_claims", None)
    if not isinstance(claims, dict):
        return jsonify({"success": False, "error": "Authentication required"}), 401
    scope, scope_error = resolve_verified_workspace_scope(
        {"hospital", "laboratory", "bioinformatics"}, access="read"
    )
    if scope_error:
        return scope_error
    org_id = scope["organisation_id"]
    role = scope["organisation_type"]
    trial_scope = False
    # The database authorisation check above grants only this read operation.
    # Do not derive application permissions from user-editable metadata or headers.
    permissions = ["intelligence:read"]

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "A JSON object is required"}), 400
        allowed = {"csv_analysis", "bioinformatics", "journey_checks", "intent"}
        if set(payload) - allowed:
            return jsonify({"success": False, "error": "Unsupported input fields"}), 400
        intent = payload.get("intent", "explain_findings")
        if intent not in {"explain_findings", "summarise", "next_steps"}:
            return jsonify({"success": False, "error": "Unsupported JC explanation intent"}), 400

        context = JCContext(
            user_id=claims["sub"],
            organisation_id=org_id,
            permissions=frozenset(permissions),
            role=role,
            clinical_trials_scope=trial_scope,
        )
        agent = JCAgent(context=context, audit=_write_jc_audit)
        agent.register(JCTool(
            name="intelligence_summary",
            description="Aggregate existing structured QC and patient-journey checks.",
            handler=lambda _ctx, args: build_intelligence_summary(
                csv_analysis=args.get("csv_analysis"),
                bioinformatics=args.get("bioinformatics"),
                journey_checks=args.get("journey_checks"),
            ),
            required_permissions=frozenset({"intelligence:read"}),
            allowed_arguments=frozenset(allowed),
        ))
        tool_payload = {key: value for key, value in payload.items() if key != "intent"}
        result = agent.execute("intelligence_summary", tool_payload)
        # The deterministic engine remains authoritative. The optional model
        # receives only its minimised summary and may explain, never alter findings.
        result["language_assistance"] = {"status": "not_configured", "authoritative": False}
        try:
            result["explanation"] = explain_jlight_evidence(result["result"], intent)
            result["language_assistance"] = {"status": "available", "authoritative": False}
        except JCProviderUnavailable:
            result["language_assistance"] = {"status": "unavailable", "authoritative": False}
        except (ValueError, JCProviderInvalidResponse):
            result["language_assistance"] = {"status": "rejected", "authoritative": False}
        return jsonify({"success": True, "organisation_id": org_id, **result}), 200
    except JCApprovalRequired:
        return jsonify({"success": False, "error": "Explicit approval required"}), 409
    except JCForbidden:
        return jsonify({"success": False, "error": "Permission denied"}), 403
    except JCInvalidRequest:
        return jsonify({"success": False, "error": "Invalid intelligence request"}), 400
    except JCError:
        return jsonify({"success": False, "error": "JC execution unavailable; check audit service"}), 503
    except Exception:
        app.logger.exception("Intelligence summary failed")
        return jsonify({"success": False, "error": "Intelligence summary unavailable"}), 503



@app.route("/api/intelligence/clinical-trials-summary", methods=["POST"])
@require_auth
def api_clinical_trials_intelligence_summary():
    """Run Clinical Trials JC against server-derived, verified database evidence."""
    claims = getattr(g, "auth_claims", None)
    if not isinstance(claims, dict):
        return jsonify({"success": False, "error": "Verified authentication required"}), 403
    scope, scope_error = resolve_verified_workspace_scope(
        {"clinical_trials"}, access="read"
    )
    if scope_error:
        return scope_error
    org_id = scope["organisation_id"]

    try:
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict) or payload:
            return jsonify({
                "success": False,
                "error": "Client-supplied trial checks are not accepted; evidence is derived from the authorised database workspace",
            }), 400

        db = get_db()
        if db is None:
            return jsonify({"success": False, "error": "Clinical Trials evidence store unavailable"}), 503
        try:
            with db.cursor() as cur:
                cur.execute(
                    "SELECT set_config('request.jwt.claim.sub', %s, true)",
                    (claims["sub"],),
                )
                cur.execute(
                    "SELECT public.jl_build_trial_intelligence_checks(%s::uuid) AS checks",
                    (org_id,),
                )
                row = cur.fetchone()
                checks = row["checks"] if row else None
            db.rollback()
        except Exception:
            db.rollback()
            raise

        if not isinstance(checks, list) or len(checks) > 20:
            return jsonify({"success": False, "error": "Server-derived Clinical Trials evidence is invalid"}), 503

        context = JCContext(
            user_id=claims["sub"],
            organisation_id=org_id,
            permissions=frozenset({"intelligence:read"}),
            role="clinical_trials",
            clinical_trials_scope=True,
        )
        agent = JCAgent(context=context, audit=_write_jc_audit)
        agent.register(JCTool(
            name="clinical_trials_summary",
            description="Aggregate de-identified Clinical Trials checks derived from authorised canonical database records.",
            handler=lambda _ctx, args: build_clinical_trials_intelligence_summary(
                clinical_trials_checks=args.get("clinical_trials_checks"),
            ),
            required_permissions=frozenset({"intelligence:read"}),
            allowed_arguments=frozenset({"clinical_trials_checks"}),
            allowed_scopes=frozenset({"clinical_trials"}),
        ))
        result = agent.execute(
            "clinical_trials_summary",
            {"clinical_trials_checks": checks},
        )
        return jsonify({"success": True, "organisation_id": org_id, **result}), 200
    except JCApprovalRequired:
        return jsonify({"success": False, "error": "Explicit approval required"}), 409
    except JCForbidden:
        return jsonify({"success": False, "error": "Permission denied"}), 403
    except JCInvalidRequest:
        return jsonify({"success": False, "error": "Invalid intelligence request"}), 400
    except JCError:
        return jsonify({"success": False, "error": "JC execution unavailable; check audit service"}), 503
    except Exception:
        app.logger.exception("Clinical Trials intelligence failed")
        return jsonify({"success": False, "error": "Clinical Trials intelligence unavailable"}), 503


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health_check():
    db = get_db()
    db_ok = False
    if db:
        try:
            with db.cursor() as cur:
                cur.execute("SELECT 1")
            db_ok = True
        except Exception:
            pass

    return success({
        "status": "healthy",
        "version": "4.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "api": "ok",
            "ml_engine": "ok",
            "bio_engine": "ok",
            "database": "ok" if db_ok else "unavailable (running in stateless mode)",
        }
    })


# ─── CSV Analysis ─────────────────────────────────────────────────────────────

@app.route("/api/analyse-csv", methods=["POST"])
@require_domain_auth({"hospital", "laboratory", "bioinformatics"}, access="write")
def api_analyse_csv():
    """
    Analyse a CSV/XLSX file for QC anomalies.
    Accepts multipart/form-data (file upload) or JSON with base64 content.
    """
    role = {
        "hospital": "Hospital",
        "laboratory": "Laboratory",
        "bioinformatics": "Bioinformatics",
    }[g.jlight_scope["organisation_type"]]

    try:
        # Handle file upload
        if request.files.get("file"):
            f = request.files["file"]
            content = f.read()
            filename = f.filename or "upload.csv"

        # Handle JSON with csvText field (from frontend)
        elif request.is_json:
            data = request.get_json()
            csv_text = data.get("csvText", "")
            filename = data.get("fileName", "upload.csv")
            if not csv_text:
                return error("No CSV data provided")
            content = csv_text.encode("utf-8")
        else:
            return error("No file or CSV data provided")

        result = analyse_csv(content, filename, role=role)

        # Keep uploaded CSV content out of the legacy global table. Analysis is
        # performed in-memory and only non-identifying metrics are logged.
        log_audit("csv_upload", role, {
            "organisation_id": g.jlight_scope["organisation_id"],
            "user_id": g.jlight_scope["user_id"],
            "row_count": result.get("rowCount", 0),
            "severity": result.get("severity", "unknown"),
            "risk_score": result.get("riskScore", 0),
        })

        return success(result)

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        app.logger.error(f"CSV analysis error: {traceback.format_exc()}")
        return error(f"Analysis failed: {str(e)}", 500)


# ─── Bioinformatics Endpoints ─────────────────────────────────────────────────

# Raw sequence analysis endpoints are intentionally not exposed by JLIGHT.
# JLIGHT ingests authorised, externally generated bioinformatics outputs and
# provides provenance, QC review and cross-domain intelligence; it is not a
# specimen analyser or a substitute for TBProfiler/BWA/GATK pipelines.

# ─── Decision Cards ───────────────────────────────────────────────────────────

@app.route("/api/cards", methods=["GET"])
@require_auth
def api_cards():
    """Fail closed until decision cards have tenant-scoped read permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)


@app.route("/api/cards/acknowledge", methods=["POST"])
@require_auth
def api_acknowledge():
    """Fail closed until decision-card writes have tenant-scoped permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)


# ─── Audit Log ────────────────────────────────────────────────────────────────

@app.route("/api/audit", methods=["GET"])
@require_auth
def api_audit():
    """Fail closed until audit-log reads have tenant-scoped permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"\n🧬 JLIGHT API v4.0 starting on port {port}")
    print(f"   Database: {'connected' if DB_AVAILABLE else 'not configured (stateless mode)'}")
    print(f"   Mode: {'development' if debug else 'production'}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
