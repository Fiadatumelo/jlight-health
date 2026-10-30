"""
JLIGHT v4 — Flask REST API
=============================
Endpoints:
  POST /api/analyse-csv       — CSV/XLSX QC analysis
  POST /api/bio/tb            — TB drug resistance screening
  POST /api/bio/variant       — Variant analysis
  POST /api/bio/ngs           — NGS QC metrics
  POST /api/bio/wgs           — WGS assembly metrics
  POST /api/bio/sequence      — Sequence analysis
  POST /api/bio/fasta         — Parse FASTA/FASTQ file
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
from agent.jc_agent import (
    JCContext, JCAgent, JCTool, JCError, JCApprovalRequired,
    JCForbidden, JCInvalidRequest,
)

from engine.bio_engine import (
    screen_tb_resistance,
    detect_variants,
    analyse_ngs_quality,
    calculate_wgs_metrics,
    analyse_sequence,
    parse_fasta,
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
        def wrapped(*args, **kwargs):
            claims = getattr(g, "auth_claims", None)
            if not isinstance(claims, dict) or not claims.get("sub"):
                return jsonify({"success": False, "error": "Verified authentication required"}), 401
            scope, scope_error = resolve_verified_workspace_scope(allowed, access=access)
            if scope_error:
                return scope_error
            g.jlight_scope = scope
            return view(*args, **kwargs)
        return wrapped
    return decorate


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

@app.route("/api/bio/tb", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_tb_resistance():
    """Screen a DNA sequence for TB drug resistance mutations."""
    try:
        data = request.get_json()
        sequence = get_json_field(data, "sequence")

        if len(sequence.replace("\n", "").replace(">", "")) < 50:
            return error("Sequence too short — minimum 50 nucleotides required")

        report = screen_tb_resistance(sequence)

        log_audit("bio_tb_resistance", g.jlight_scope["organisation_type"], {
            "seq_length": report.sequence_length,
            "who_category": report.who_category,
            "resistant_count": len(report.resistant_mutations),
        })

        return success({"report": report.to_dict()})

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        app.logger.error(f"TB resistance error: {traceback.format_exc()}")
        return error(str(e), 500)


@app.route("/api/bio/variant", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_variant():
    """Detect variants between reference and sample sequences."""
    try:
        data = request.get_json()
        ref = get_json_field(data, "reference")
        sample = get_json_field(data, "sample")

        if len(ref.replace("\n", "")) < 10 or len(sample.replace("\n", "")) < 10:
            return error("Sequences too short — minimum 10 nucleotides each")

        report = detect_variants(ref, sample)

        log_audit("bio_variant", data.get("role", ""), {
            "total_variants": report.total_variants,
            "snvs": report.snvs,
            "indels": report.indels,
        })

        return success({"report": report.to_dict()})

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        return error(str(e), 500)


@app.route("/api/bio/ngs", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_ngs():
    """Compute NGS QC metrics from sequences or file."""
    try:
        sequences = []
        quality_scores = []
        filename = "upload"

        if request.files.get("file"):
            f = request.files["file"]
            filename = f.filename or "reads.fastq"
            records = parse_fasta(f.read())
            sequences = [r["sequence"] for r in records]
            quality_scores = [r["quality"] for r in records if r.get("quality")]

        elif request.is_json:
            data = request.get_json()
            sequences = data.get("sequences", [])
            quality_scores = data.get("quality_scores", [])

        if not sequences:
            sequences = ["ATCGATCGATCG" * 10]  # Demo

        result = analyse_ngs_quality(sequences, quality_scores or None)
        return success({"result": result.to_dict(), "filename": filename})

    except Exception as e:
        return error(str(e), 500)


@app.route("/api/bio/wgs", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_wgs():
    """Calculate WGS assembly metrics (N50, L50, etc.)."""
    try:
        sequences_or_lengths = []
        filename = "assembly"

        if request.files.get("file"):
            f = request.files["file"]
            filename = f.filename or "assembly.fasta"
            records = parse_fasta(f.read())
            sequences_or_lengths = [r["sequence"] for r in records if r["sequence"]]

        elif request.is_json:
            data = request.get_json()
            sequences_or_lengths = data.get("lengths") or data.get("sequences") or []

        if not sequences_or_lengths:
            return error("No contig sequences or lengths provided")

        result = calculate_wgs_metrics(sequences_or_lengths)
        return success({"result": result.to_dict(), "filename": filename})

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        return error(str(e), 500)


@app.route("/api/bio/sequence", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_sequence():
    """Full sequence analysis: GC%, ORFs, Tm, MW, reverse complement."""
    try:
        data = request.get_json()
        sequence = get_json_field(data, "sequence")

        result = analyse_sequence(sequence)
        return success({"result": result.to_dict()})

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        return error(str(e), 500)


@app.route("/api/bio/fasta", methods=["POST"])
@require_domain_auth({"bioinformatics"}, access="write")
def api_fasta():
    """Parse a FASTA/FASTQ file and return records."""
    try:
        if not request.files.get("file"):
            return error("No file provided")
        f = request.files["file"]
        records = parse_fasta(f.read())
        return success({
            "record_count": len(records),
            "records": records[:100],  # Cap at 100 records in response
            "filename": f.filename,
        })
    except Exception as e:
        return error(str(e), 500)


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
