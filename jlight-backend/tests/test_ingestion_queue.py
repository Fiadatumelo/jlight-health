"""Synthetic-only tests for durable queue validation and retry lifecycle."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.ingestion_queue import enqueue_export, claim_exports, finish_export


class Cursor:
    def __init__(self, db): self.db, self.row, self.rows = db, None, []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None):
        self.db.calls.append((sql, params))
        if "INSERT INTO jlight_ingestion_queue" in sql:
            self.row = self.db.insert_row if self.db.insert_row else None
        elif "SELECT id, status, source_system" in sql:
            self.row = self.db.existing_row
        elif "RETURNING q.id" in sql:
            self.rows = self.db.claimed_rows
        elif "RETURNING status, attempts" in sql:
            self.row = self.db.finish_row
    def fetchone(self): return self.row
    def fetchall(self): return self.rows


class DB:
    def __init__(self):
        self.calls, self.commits, self.rollbacks = [], 0, 0
        self.insert_row = (1, "pending")
        self.existing_row = (1, "pending", "synthetic-his", "hospital", "fhir", {"resourceType":"Bundle"})
        self.claimed_rows = [(1, "idem-1", "synthetic-his", "hospital", "fhir",
                              {"resourceType":"Bundle"}, 1, 5, "lease-1")]
        self.finish_row = ("retry", 1, 5)
    def cursor(self): return Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class IngestionQueueTests(unittest.TestCase):
    def test_enqueue_sets_tenant_context_and_persists(self):
        db = DB()
        result = enqueue_export(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1",
                                source_system="synthetic-his", domain="hospital",
                                export_format="fhir", payload={"resourceType":"Bundle"},
                                idempotency_key="idem-1")
        self.assertEqual(result["action"], "queued")
        self.assertIn("set_config('jlight.organization_id'", db.calls[0][0])
        self.assertEqual(db.commits, 1)

    def test_clinical_trials_rejected(self):
        with self.assertRaisesRegex(ValueError, "separate workflow"):
            enqueue_export(DB(), "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1",
                           source_system="synthetic", domain="clinical_trials",
                           export_format="fhir", payload={"x":1}, idempotency_key="k")

    def test_idempotency_collision_with_changed_payload_is_held(self):
        db = DB()
        db.insert_row = None
        db.existing_row = (1, "pending", "synthetic-his", "hospital", "fhir", {"resourceType":"Different"})
        with self.assertRaisesRegex(ValueError, "manual review"):
            enqueue_export(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1",
                           source_system="synthetic-his", domain="hospital",
                           export_format="fhir", payload={"resourceType":"Bundle"}, idempotency_key="idem-1")

    def test_claim_uses_skip_locked_and_lease(self):
        db = DB()
        rows = claim_exports(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1")
        self.assertEqual(rows[0]["lease_token"], "lease-1")
        self.assertIn("SKIP LOCKED", next(sql for sql, _ in db.calls if "RETURNING q.id" in sql))
        self.assertEqual(db.commits, 1)

    def test_finish_rejects_stale_lease(self):
        db = DB()
        db.finish_row = None
        with self.assertRaisesRegex(ValueError, "lease is missing"):
            finish_export(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", 1, "old-lease",
                          success=True)

    def test_failed_attempt_schedules_retry(self):
        db = DB()
        result = finish_export(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", 1, "lease-1",
                               success=False, error_code="temporary_source_error")
        self.assertEqual(result["status"], "retry")
        self.assertIn("max_attempts", next(sql for sql, _ in db.calls if "RETURNING status, attempts" in sql))


if __name__ == "__main__":
    unittest.main(verbosity=2)
