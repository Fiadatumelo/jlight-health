"""Opt-in staging catalog inspection. Never queries clinical rows or changes SQL state.

Run: python jlight-backend/scripts/inspect_bioinformatics_schema.py
An absent connection reports BLOCKED; it never substitutes a mock schema.
"""
import json
import os
import re

EXPECTED_STAGING_REF = "ampkysrzliwjtvbigsvu"
TABLES = ["jl_patients", "jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"]
MIGRATIONS = ["20261031000100", "20261108170100"]

# Catalog-only queries, scoped to the established tables. SQL expressions in
# output have literal values removed; function bodies and row data are excluded.
CATALOGS = {
    "tables": """SELECT c.relname AS table_name, c.relkind, c.relrowsecurity AS rls_enabled,
        c.relforcerowsecurity AS rls_forced, pg_get_userbyid(c.relowner) AS owner
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname""",
    "columns": """SELECT c.relname AS table_name,a.attname AS column_name,
        format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null,
        pg_get_expr(d.adbin,d.adrelid) AS default_expression
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname,a.attnum""",
    "constraints": """SELECT c.relname AS table_name,k.conname AS constraint_name,
        k.contype AS constraint_type,k.condeferrable,k.condeferred,k.convalidated,
        pg_get_constraintdef(k.oid) AS definition
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname,k.conname""",
    "indexes": """SELECT c.relname AS table_name,i.indisunique,i.indisvalid,
        pg_get_indexdef(i.indexrelid) AS definition
        FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname,i.indexrelid""",
    "policies": """SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
        FROM pg_policies WHERE schemaname='public' AND tablename=ANY(%s)
        ORDER BY tablename,policyname""",
    "visible_grants": """SELECT table_name,grantee,privilege_type,is_grantable
        FROM information_schema.table_privileges
        WHERE table_schema='public' AND table_name=ANY(%s)
        ORDER BY table_name,grantee,privilege_type""",
    "triggers": """SELECT c.relname AS table_name,t.tgname,t.tgenabled,
        pg_get_triggerdef(t.oid) AS definition
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname""",
}


def redact_literals(value):
    """Do not export literal constants embedded in defaults/policies/triggers."""
    if isinstance(value, str):
        value = re.sub(r"\$(\w*)\$.*?\$\1\$", "<literal>", value, flags=re.S)
        return re.sub(r"'(?:[^'\\]|\\.|'')*'", "'<literal>'", value)
    if isinstance(value, dict):
        return {key: redact_literals(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_literals(item) for item in value]
    return value


def inspect_schema(environ=None, connect=None):
    env = os.environ if environ is None else environ
    result = {"status": "BLOCKED", "catalog_only": True, "live_workflow_verified": False}
    dsn = env.get("JLIGHT_STAGING_DATABASE_URL", "")
    if not dsn:
        return {**result, "reason": "JLIGHT_STAGING_DATABASE_URL is not configured; no connection attempted."}
    if env.get("JLIGHT_STAGING_PROJECT_REF", EXPECTED_STAGING_REF) != EXPECTED_STAGING_REF:
        return {**result, "reason": "Configured staging project does not match the repository staging gate."}
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        return {**result, "reason": "Implicit libpq host/service overrides must be absent for staging inspection."}
    try:
        import psycopg2
        from psycopg2.extensions import parse_dsn
        from psycopg2.extras import RealDictCursor
    except ImportError:
        return {**result, "reason": "Install the existing backend requirements to enable catalog inspection."}
    try:
        config = parse_dsn(dsn)
        host, user = config.get("host", ""), config.get("user", "")
        direct = host == "db." + EXPECTED_STAGING_REF + ".supabase.co"
        pooler = bool(re.fullmatch(r"[a-zA-Z0-9.-]+\.pooler\.supabase\.com", host)) and bool(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\." + EXPECTED_STAGING_REF, user)
        )
        if (not (direct or pooler) or config.get("hostaddr") or config.get("service")
                or config.get("sslmode", "require") not in ("require", "verify-ca", "verify-full")):
            return {**result, "reason": "Connection does not satisfy the pinned staging host and TLS checks."}
    except Exception:
        return {**result, "reason": "Staging connection configuration is invalid; details withheld."}
    connection = None
    try:
        connection = (connect or psycopg2.connect)(
            dsn, connect_timeout=10, cursor_factory=RealDictCursor,
            sslmode=config.get("sslmode", "require"),
            options="-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000",
        )
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()["transaction_read_only"] != "on":
                return {**result, "reason": "Read-only transaction could not be verified; inspection refused."}
            cursor.execute("""SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user""")
            result["connection_role_properties"] = dict(cursor.fetchone())
            for name, query in CATALOGS.items():
                cursor.execute(query, (TABLES,))
                result[name] = [dict(row) for row in cursor.fetchall()]
            cursor.execute("""SELECT n.nspname,p.proname,p.prosecdef,
                pg_get_userbyid(p.proowner) AS owner,p.proacl,
                ARRAY(SELECT setting FROM unnest(p.proconfig) setting
                      WHERE setting LIKE 'search_path=%') AS search_path
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE (n.nspname='private' AND p.proname='jl_current_org_id')
                   OR (n.nspname='public' AND p.proname='jlight_has_domain_permission')
                ORDER BY n.nspname,p.proname""")
            result["permission_helpers"] = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT to_regclass('supabase_migrations.schema_migrations') AS ledger")
            if cursor.fetchone()["ledger"]:
                cursor.execute("SELECT version FROM supabase_migrations.schema_migrations WHERE version=ANY(%s) ORDER BY version", (MIGRATIONS,))
                result["recorded_migration_versions"] = [row["version"] for row in cursor.fetchall()]
            else:
                result["recorded_migration_versions"] = None
            present = {row["table_name"] for row in result["tables"]}
            result["missing_tables"] = sorted(set(TABLES) - present)
            result["status"] = "INCOMPLETE_SCHEMA" if result["missing_tables"] else "CATALOG_INSPECTED"
            result["limitations"] = [
                "Catalog presence is not authenticated API, RLS or workflow validation.",
                "Literal values are redacted; visible grants depend on the connecting role.",
                "Lineage, variant, report and immutable audit authority still require reconciliation.",
            ]
        return redact_literals(result)
    except Exception:
        # Never emit driver exception messages, DSNs, credentials or row contents.
        return {"status": "BLOCKED", "catalog_only": True, "live_workflow_verified": False,
                "reason": "Staging catalog inspection failed; connection or catalog privileges require verification."}
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            finally:
                try:
                    connection.close()
                except Exception:
                    pass


if __name__ == "__main__":
    outcome = inspect_schema()
    print(json.dumps(outcome, indent=2))
    raise SystemExit(0 if outcome["status"] == "CATALOG_INSPECTED" else 2)
