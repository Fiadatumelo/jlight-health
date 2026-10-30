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


# ─── Decision Cards ───────────────────────────────────────────────────────────

@app.route("/api/cards", methods=["GET"])
@require_auth
@app.route("/api/cards", methods=["GET"])
@require_auth
def api_cards():
    """Fail closed until decision cards have tenant-scoped read permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)

@app.route("/api/cards/acknowledge", methods=["POST"])
@require_auth
@app.route("/api/cards/acknowledge", methods=["POST"])
@require_auth
def api_acknowledge():
    """Fail closed until decision-card writes have tenant-scoped permissions."""
    return error("This endpoint is unavailable until organisation-scoped permissions are configured.", 503)

# ─── Audit Log ────────────────────────────────────────────────────────────────

@app.route("/api/audit", methods=["GET"])
@require_auth
@app.route("/api/audit", methods=["GET"])
@require_auth
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
