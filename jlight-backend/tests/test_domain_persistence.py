"""Synthetic-only unit tests for JLIGHT persistence validation and conflict handling."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.domain_persistence import payload_digest, persist_source_record, persist_workflow_event


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None
        self.results = []

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        if "SELECT payload_sha256" in sql:
            self.results = list(self.connection.same_timestamp)
        elif "INSERT INTO jlight_source_record_versions" in sql:
            self.result = (101,) if not self.connection.insert_conflict else None
        elif "INSERT INTO jlight_workflow_events" in sql:
            self.result = (202,) if not self.connection.insert_conflict else None
        else:
            self.result = None

    def fetchall(self): return self.results
    def fetchone(self): return self.result


class FakeConnection:
    def __init__(self, same_timestamp=(), insert_conflict=False):
        self.same_timestamp = same_timestamp
        self.insert_conflict = insert_conflict
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self): return FakeCursor(self)
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


def source_record(**updates):
    record = {
        "source_system": "synthetic-lis", "source_record_id": "ORD-SYN-1",
        "domain": "laboratory", "record_type": "order_status",
        "source_updated_at": "2026-10-23T09:00:00Z",
        "data": {"synthetic": True, "status": "received"},
        "jlight_patient_id": "JL-SYN-001", "link_status": "verified",
    }
    record.update(updates)
    return record


class DomainPersistenceTests(unittest.TestCase):
    def test_digest_is_stable_for_object_key_order(self):
        self.assertEqual(payload_digest({"a": 1, "b": 2}), payload_digest({"b": 2, "a": 1}))

    def test_invalid_organization_id_rejected_before_database_access(self):
        db = FakeConnection()
        with self.assertRaisesRegex(ValueError, "organization_id must be a UUID"):
            persist_source_record(db, "not-an-id", source_record())
        self.assertEqual(db.calls, [])

    def test_clinical_trials_rejected_from_shared_patient_store(self):
        with self.assertRaisesRegex(ValueError, "separate workflow"):
            persist_source_record(FakeConnection(), "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1",
                                  source_record(domain="clinical_trials"))

    def test_first_synthetic_record_appended_and_tenant_context_set(self):
        db = FakeConnection()
        result = persist_source_record(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", source_record())
        self.assertEqual(result["action"], "insert")
        self.assertIn("set_config('jlight.organization_id'", db.calls[0][0])
        self.assertEqual(db.commits, 1)
        insert = next(sql for sql, _ in db.calls if "INSERT INTO jlight_source_record_versions" in sql)
        self.assertIn("ON CONFLICT", insert)

    def test_exact_same_timestamp_payload_is_idempotent(self):
        digest = payload_digest(source_record()["data"])
        db = FakeConnection(same_timestamp=[(digest,)])
        result = persist_source_record(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", source_record())
        self.assertEqual(result["action"], "duplicate_noop")
        self.assertEqual(db.commits, 1)

    def test_changed_payload_at_same_timestamp_is_held(self):
        db = FakeConnection(same_timestamp=[("0" * 64,)])
        result = persist_source_record(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", source_record())
        self.assertEqual(result["action"], "conflict_hold")
        self.assertTrue(result["requires_review"])
        insert_params = next(params for sql, params in db.calls if "INSERT INTO jlight_source_record_versions" in sql)
        self.assertIsNone(insert_params[8])
        self.assertFalse(insert_params[9])

    def test_workflow_events_are_insert_only_and_idempotent(self):
        event = {
            "event_id": "EV-SYN-1", "source_system": "synthetic-lis",
            "source_record_id": "ORD-SYN-1", "domain": "laboratory",
            "event_type": "order_received", "observed_at": "2026-10-23T09:00:00Z",
            "jlight_patient_id": "JL-SYN-001", "link_status": "verified",
        }
        db = FakeConnection()
        result = persist_workflow_event(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", event)
        self.assertEqual(result["action"], "insert")
        insert = next(sql for sql, _ in db.calls if "INSERT INTO jlight_workflow_events" in sql)
        self.assertIn("ON CONFLICT", insert)
        self.assertNotIn("UPDATE jlight_workflow_events", insert)

    def test_transaction_rolls_back_on_database_error(self):
        class BrokenConnection(FakeConnection):
            def cursor(self): raise RuntimeError("synthetic database failure")
        db = BrokenConnection()
        with self.assertRaisesRegex(RuntimeError, "synthetic database failure"):
            persist_source_record(db, "8d49b3d1-c4f6-4d5a-9a43-0a42b65c29e1", source_record())
        self.assertEqual(db.rollbacks, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
