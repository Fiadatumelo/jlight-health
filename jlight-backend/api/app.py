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
    app_metadata = claims.get("app_metadata") if isinstance(claims, dict) else {}
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
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        return jsonify({"success": False, "error": "Verified permissions required"}), 403
    if trial_scope:
        return jsonify({"success": False, "error": "JC intelligence is not enabled for Clinical Trials scope"}), 403

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
    """Run the isolated Clinical Trials JC tool using verified trial scope."""
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
@require_auth
def api_analyse_csv():
    """
    Analyse a CSV/XLSX file for QC anomalies.
    Accepts multipart/form-data (file upload) or JSON with base64 content.
    """
    role = request.headers.get("X-Role", "Laboratory & Research")

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
            role = data.get("role", role)
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

        # Save to DB if available
        db = get_db()
        if db and result.get("success"):
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """INSERT INTO csv_uploads
                           (file_name, file_size_kb, row_count, column_count,
                            detected_columns, analysis_result, severity, risk_score)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            filename,
                            round(len(content) / 1024),
                            result.get("rowCount", 0),
                            result.get("columnCount", 0),
                            json.dumps(result.get("detectedColumns", {})),
                            json.dumps({"severity": result.get("severity"), "riskScore": result.get("riskScore")}),
                            result.get("severity", "stable"),
                            result.get("riskScore", 0),
                        )
                    )
                db.commit()
            except Exception:
                pass

        return success(result)

    except ValueError as e:
        return error(str(e))
    except Exception as e:
        app.logger.error(f"CSV analysis error: {traceback.format_exc()}")
        return error(f"Analysis failed: {str(e)}", 500)


# ─── Bioinformatics Endpoints ─────────────────────────────────────────────────

@app.route("/api/bio/tb", methods=["POST"])
@require_auth
def api_tb_resistance():
    """Screen a DNA sequence for TB drug resistance mutations."""
    try:
        data = request.get_json()
        sequence = get_json_field(data, "sequence")

        if len(sequence.replace("\n", "").replace(">", "")) < 50:
            return error("Sequence too short — minimum 50 nucleotides required")

        report = screen_tb_resistance(sequence)

        log_audit("bio_tb_resistance", data.get("role", ""), {
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
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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
    """Return decision cards from DB or static data."""
    role = request.args.get("role", "")
    db = get_db()

    if db:
        try:
            with db.cursor() as cur:
                if role:
                    category = "lab" if "lab" in role.lower() or "laboratory" in role.lower() else \
                               "trial" if "trial" in role.lower() else \
                               "hosp" if "hosp" in role.lower() else ""
                    if category:
                        cur.execute(
                            "SELECT * FROM decision_cards WHERE (category=%s OR category='all') AND status!='archived' ORDER BY created_at DESC",
                            (category,)
                        )
                    else:
                        cur.execute("SELECT * FROM decision_cards WHERE status!='archived' ORDER BY created_at DESC")
                else:
                    cur.execute("SELECT * FROM decision_cards WHERE status!='archived' ORDER BY created_at DESC")
                cards = cur.fetchall()
                return success({"cards": [dict(c) for c in cards], "source": "database"})
        except Exception:
            pass

    return success({"cards": [], "source": "static", "note": "Database unavailable"})


@app.route("/api/cards/acknowledge", methods=["POST"])
@require_auth
def api_acknowledge():
    """Acknowledge a decision card."""
    try:
        data = request.get_json()
        card_number = get_json_field(data, "card_number")
        role = data.get("role", "")

        db = get_db()
        if db:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE decision_cards SET status='resolved', updated_at=%s WHERE card_number=%s",
                    (datetime.now(timezone.utc), card_number)
                )
            db.commit()

        log_audit("card_acknowledged", role, {
            "card_number": card_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return success({"card_number": card_number, "status": "resolved"})

    except Exception as e:
        return error(str(e), 500)


# ─── Audit Log ────────────────────────────────────────────────────────────────

@app.route("/api/audit", methods=["GET"])
@require_auth
def api_audit():
    """Return recent audit log entries."""
    db = get_db()
    if not db:
        return success({"entries": [], "note": "Database unavailable"})
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100"
            )
            entries = cur.fetchall()
        return success({"entries": [dict(e) for e in entries]})
    except Exception as e:
        return error(str(e), 500)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "production") == "development"
    print(f"\n🧬 JLIGHT API v4.0 starting on port {port}")
    print(f"   Database: {'connected' if DB_AVAILABLE else 'not configured (stateless mode)'}")
    print(f"   Mode: {'development' if debug else 'production'}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
