"""Synthetic tests for the read-only inspector, not evidence of a deployed schema."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "inspect_bioinformatics_schema.py"
spec = importlib.util.spec_from_file_location("schema_inspection", SOURCE)
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)
STAGING = "postgresql://postgres@db.ampkysrzliwjtvbigsvu.supabase.co/postgres"


class SyntheticConnection:
    def __init__(self, readonly="on", fail=False):
        self.readonly = readonly
        self.fail = fail
        self.queries = []
        self.rolled_back = self.closed = False

    def set_session(self, **kwargs):
        assert kwargs == {"readonly": True, "autocommit": False}

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.fail:
            raise RuntimeError("sensitive-synthetic-sentinel")

    def fetchone(self):
        query = self.queries[-1][0]
        if query.startswith("SHOW"):
            return {"transaction_read_only": self.readonly}
        if "to_regclass" in query:
            return {"ledger": None}
        return {"rolsuper": False, "rolbypassrls": False}

    def fetchall(self):
        return []  # Intentionally no invented canonical schema or evidence rows.

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_missing_configuration_never_connects():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Missing configuration must not connect")
    result = inspector.inspect_schema({}, connect=forbidden)
    assert result["status"] == "BLOCKED"
    assert result["live_workflow_verified"] is False
    assert "tables" not in result


def test_nonstaging_connections_are_rejected_before_connect():
    for url in ("postgresql://postgres@db.other.supabase.co/postgres",
                STAGING + "?hostaddr=127.0.0.1", STAGING + "?sslmode=disable",
                "postgresql://postgres@aws-0-region.pooler.supabase.com/postgres"):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Unverified target must not connect")
        assert inspector.inspect_schema({"JLIGHT_STAGING_DATABASE_URL": url}, forbidden)["status"] == "BLOCKED"


def test_explicit_wrong_project_is_rejected():
    assert inspector.inspect_schema({"JLIGHT_STAGING_DATABASE_URL": STAGING,
                                    "JLIGHT_STAGING_PROJECT_REF": "other"})["status"] == "BLOCKED"


def test_catalog_only_missing_objects_are_reported_honestly():
    db = SyntheticConnection()
    def connect(_dsn, **kwargs):
        assert "default_transaction_read_only=on" in kwargs["options"]
        assert kwargs["connect_timeout"] == 10
        assert kwargs["sslmode"] == "require"
        return db
    result = inspector.inspect_schema({"JLIGHT_STAGING_DATABASE_URL": STAGING}, connect)
    assert result["status"] == "INCOMPLETE_SCHEMA"
    assert result["missing_tables"] == sorted(inspector.TABLES)
    assert result["live_workflow_verified"] is False
    assert db.rolled_back and db.closed
    assert len(db.queries) > 2
    assert all("FROM public." not in query for query, _ in db.queries)
    assert all(query.lstrip().startswith(("SELECT", "SHOW")) for query, _ in db.queries)


def test_readonly_mode_is_verified_before_catalog_queries():
    db = SyntheticConnection(readonly="off")
    result = inspector.inspect_schema({"JLIGHT_STAGING_DATABASE_URL": STAGING}, lambda *_a, **_kw: db)
    assert result["status"] == "BLOCKED"
    assert len(db.queries) == 1
    assert db.rolled_back and db.closed


def test_driver_errors_are_sanitised_and_cleanup_runs():
    db = SyntheticConnection(fail=True)
    result = inspector.inspect_schema({"JLIGHT_STAGING_DATABASE_URL": STAGING}, lambda *_a, **_kw: db)
    assert result["status"] == "BLOCKED"
    assert "sensitive-synthetic-sentinel" not in str(result)
    assert STAGING not in str(result)
    assert db.rolled_back and db.closed


def test_sql_literals_are_not_exported():
    value = {"definition": "CHECK (note = 'synthetic private text')", "body": "$$synthetic private text$$"}
    assert "synthetic private text" not in str(inspector.redact_literals(value))
