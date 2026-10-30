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
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_cors import CORS

from engine.intelligence_engine import build_intelligence_summary, build_clinical_trials_intelligence_summary
from agent.jc_agent import (
    JCContext, JCAgent, JCTool, JCError, JCApprovalRequired,
    JCForbidden, JCInvalidRequest,
)
import jwt
from api.security import verify_access_token

from engine.csv_engine import analyse_csv
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


@app.before_request
def require_verified_supabase_session():
    """Fail closed for API routes; health remains public for deployment probes."""
    if request.method == "OPTIONS" or request.path == "/api/health":
        return None
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return jsonify({"success": False, "error": "Authentication required"}), 401
    try:
        claims = verify_access_token(token.strip())
        if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
            return jsonify({"success": False, "error": "Invalid session"}), 401
        g.auth_claims = claims
        g.auth_user_id = claims["sub"]
        # Legacy global audit/cards tables have no demonstrated tenant-scoped
        # permission contract. Keep them unavailable rather than leak cross-tenant data.
        if request.path in {"/api/audit", "/api/cards", "/api/cards/acknowledge"}:
            return jsonify({
                "success": False,
                "error": "This endpoint is unavailable until organisation-scoped permissions are configured."
            }), 503
    except RuntimeError:
        app.logger.exception("Supabase JWT verification is not configured")
        return jsonify({"success": False, "error": "Authentication service unavailable"}), 503
    except jwt.PyJWTError:
        return jsonify({"success": False, "error": "Invalid or expired session"}), 401
    except Exception:
        app.logger.exception("Unexpected token verification failure")
        return jsonify({"success": False, "error": "Authentication service unavailable"}), 503
    return None


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

def resolve_verified_workspace_scope(allowed_domains, access="read"):
    """Resolve organisation and path from the database, never from browser-supplied roles."""
    claims = getattr(g, "auth_claims", None)
    user_id = claims.get("sub") if isinstance(claims, dict) else None
    if not user_id:
        return None, (jsonify({"success": False, "error": "Verified authentication required"}), 401)
    db = get_db()
    if db is None:
        return None, (jsonify({"success": False, "error": "Organisation authorization service unavailable"}), 503)
    try:
        with db.cursor() as cur:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            cur.execute(
                """SELECT p.org_id::text AS organisation_id,
                          lower(coalesce(nullif(o.type, 'multi'), o.role)) AS organisation_type
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
            org_type = row["organisation_type"]
            if org_type not in set(allowed_domains):
                db.rollback()
                return None, (jsonify({"success": False, "error": "This organisation is not authorised for the requested workspace"}), 403)
            cur.execute(
                "SELECT public.jlight_has_domain_permission(%s::uuid, %s, %s) AS allowed",
                (org_id, org_type, access),
            )
            permission_row = cur.fetchone()
            allowed = bool(permission_row and permission_row["allowed"])
        db.rollback()
        if not allowed:
            return None, (jsonify({"success": False, "error": "Workspace permission denied"}), 403)
        return {"organisation_id": org_id, "organisation_type": org_type, "user_id": user_id}, None
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        app.logger.exception("Organisation path authorization failed")
        return None, (jsonify({"success": False, "error": "Organisation authorization service unavailable"}), 503)


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
def api_intelligence_summary():
    """Run the deterministic intelligence summary through JC under verified scope."""
    claims = getattr(g, "auth_claims", None)
    if not isinstance(claims, dict):
        return jsonify({"success": False, "error": "Authentication required"}), 401

    # Supabase app_metadata is server-managed and signed into the access token.
    # Never authorise from user_metadata, which users can edit themselves.
    app_metadata = claims.get("app_metadata")
    app_metadata = app_metadata if isinstance(app_metadata, dict) else {}
    org_id = (
        claims.get("organisation_id") or claims.get("org_id")
        or app_metadata.get("organisation_id") or app_metadata.get("org_id")
    )
    permissions = claims.get("permissions")
    if permissions is None:
        permissions = app_metadata.get("permissions", [])
    token_role = str(claims.get("role", "")).strip().lower()
    # Supabase's standard database roles are not JLIGHT workspace roles.
    custom_top_level_role = token_role if token_role not in {"authenticated", "anon", "service_role"} else ""
    role = str(
        claims.get("jlight_role") or claims.get("workspace_role")
        or app_metadata.get("jlight_role") or app_metadata.get("workspace_role")
        or app_metadata.get("role") or custom_top_level_role or ""
    ).strip().lower()
    trial_scope = (
        role in {"trial", "clinical_trials"}
        or claims.get("clinical_trials_scope") is True
        or app_metadata.get("clinical_trials_scope") is True
    )
    if not isinstance(org_id, str) or not org_id.strip():
        return jsonify({"success": False, "error": "Verified organisation scope required"}), 403
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        return jsonify({"success": False, "error": "Verified permissions required"}), 403
    if trial_scope:
        return jsonify({"success": False, "error": "JC intelligence is not enabled for Clinical Trials scope"}), 403

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "A JSON object is required"}), 400
        # Only the engine's structured input fields are accepted. Never forward
        # identifiers, filenames, raw sequences, free text, or trial data.
        allowed = {"csv_analysis", "bioinformatics", "journey_checks"}
        if set(payload) - allowed:
            return jsonify({"success": False, "error": "Unsupported input fields"}), 400
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
        result = agent.execute("intelligence_summary", payload)
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
def api_clinical_trials_intelligence_summary():
    """Run the isolated Clinical Trials JC tool using verified trial scope.

    Authentication is enforced by require_verified_supabase_session before this
    handler executes; this route adds the trial-specific tenant and permission gate.
    """
    claims = getattr(g, "auth_claims", None)
    if not isinstance(claims, dict):
        return jsonify({"success": False, "error": "Verified authentication required"}), 403
    app_metadata = claims.get("app_metadata")
    app_metadata = app_metadata if isinstance(app_metadata, dict) else {}
    org_id = (
        claims.get("organisation_id") or claims.get("org_id")
        or app_metadata.get("organisation_id") or app_metadata.get("org_id")
    )
    permissions = claims.get("permissions")
    if permissions is None:
        permissions = app_metadata.get("permissions", [])
    token_role = str(claims.get("role", "")).strip().lower()
    custom_role = token_role if token_role not in {"authenticated", "anon", "service_role"} else ""
    role = str(
        claims.get("jlight_role") or claims.get("workspace_role")
        or app_metadata.get("jlight_role") or app_metadata.get("workspace_role")
        or app_metadata.get("role") or custom_role or ""
    ).strip().lower()
    trial_scope = (
        role in {"trial", "clinical_trials"}
        or claims.get("clinical_trials_scope") is True
        or app_metadata.get("clinical_trials_scope") is True
    )
    if not isinstance(org_id, str) or not org_id.strip():
        return jsonify({"success": False, "error": "Verified organisation scope required"}), 403
    if not trial_scope:
        return jsonify({"success": False, "error": "Clinical Trials workspace scope required"}), 403
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        return jsonify({"success": False, "error": "Verified permissions required"}), 403
    if "intelligence:read" not in permissions:
        return jsonify({"success": False, "error": "Permission denied"}), 403

    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"clinical_trials_checks"}:
            return jsonify({"success": False, "error": "Only clinical_trials_checks is accepted"}), 400
        checks = payload.get("clinical_trials_checks")
        if not isinstance(checks, list) or len(checks) > 20:
            return jsonify({"success": False, "error": "A bounded list of trial checks is required"}), 400
        allowed_fields = {"check_id", "status", "severity", "evidence_count"}
        if any(not isinstance(item, dict) or set(item) - allowed_fields for item in checks):
            return jsonify({"success": False, "error": "Trial checks contain unsupported fields"}), 400

        context = JCContext(
            user_id=claims["sub"],
            organisation_id=org_id,
            permissions=frozenset(permissions),
            role=role,
            clinical_trials_scope=True,
        )
        agent = JCAgent(context=context, audit=_write_jc_audit)
        agent.register(JCTool(
            name="clinical_trials_summary",
            description="Aggregate de-identified Clinical Trials workflow checks only.",
            handler=lambda _ctx, args: build_clinical_trials_intelligence_summary(
                clinical_trials_checks=args.get("clinical_trials_checks"),
            ),
            required_permissions=frozenset({"intelligence:read"}),
            allowed_arguments=frozenset({"clinical_trials_checks"}),
            allowed_scopes=frozenset({"clinical_trials"}),
        ))
        result = agent.execute("clinical_trials_summary", payload)
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
        "service": "JLIGHT Health Intelligence System",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "api": "ok",
            "ml_engine": "ok",
            "database": "ok" if db_ok else "unavailable (running in stateless mode)",
        }
    })


# ─── CSV Analysis ─────────────────────────────────────────────────────────────

@app.route("/api/analyse-csv", methods=["POST"])
def api_analyse_csv():
    """
    Analyse a CSV/XLSX file for QC anomalies.
    Accepts multipart/form-data (file upload) or JSON with base64 content.
    """
    scope, scope_error = resolve_verified_workspace_scope(
        {"hospital", "laboratory", "bioinformatics"}, access="write"
    )
    if scope_error:
        return scope_error
    role = {
        "hospital": "Hospital",
        "laboratory": "Laboratory",
        "bioinformatics": "Bioinformatics",
    }[scope["organisation_type"]]

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

        # Log to audit trail
        log_audit("csv_upload", role, {
            "filename": filename,
            "row_count": result.get("rowCount", 0),
            "severity": result.get("severity", "unknown"),
            "risk_score": result.get("riskScore", 0),
        })

        # CSV payloads are analysed in-memory only. Persisting them in the
        # legacy global csv_uploads table would mix organisation data.
        log_audit("csv_upload", role, {
            "organisation_id": scope["organisation_id"],
            "user_id": scope["user_id"],
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


# ─── Decision Cards ───────────────────────────────────────────────────────────

@app.route("/api/cards", methods=["GET"])
def api_cards():
    """Fail closed until decision cards have tenant-scoped read permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)

@app.route("/api/cards/acknowledge", methods=["POST"])
def api_acknowledge():
    """Fail closed until decision-card writes have tenant-scoped permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)

# ─── Audit Log ────────────────────────────────────────────────────────────────

@app.route("/api/audit", methods=["GET"])
def api_audit():
    """Fail closed until audit-log reads have tenant-scoped permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"\nJLIGHT Health Intelligence API starting on port {port}")
    print(f"   Database: {'connected' if DB_AVAILABLE else 'not configured (stateless mode)'}")
    print(f"   Mode: {'development' if debug else 'production'}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
