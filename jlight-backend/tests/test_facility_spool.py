import os, sqlite3, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scripts.facility_spool import connect, enqueue, replay

class Response:
    status=202
    def __enter__(self): return self
    def __exit__(self,*args): return False

class FacilitySpoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=connect(os.path.join(self.tmp.name,"spool.sqlite3"))
    def tearDown(self):
        self.db.close(); self.tmp.cleanup()
    def test_enqueue_survives_reopen_and_is_idempotent(self):
        key=enqueue(self.db,source_system="synthetic-his",domain="hospital",export_format="fhir",payload={"resourceType":"Bundle"})
        self.db.close(); self.db=connect(os.path.join(self.tmp.name,"spool.sqlite3"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM spool WHERE status='pending'").fetchone()[0],1)
        key2=enqueue(self.db,source_system="synthetic-his",domain="hospital",export_format="fhir",payload={"resourceType":"Bundle"})
        self.assertEqual(key,key2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM spool").fetchone()[0],1)
    def test_rejects_clinical_trials(self):
        with self.assertRaisesRegex(ValueError,"separate workflow"):
            enqueue(self.db,source_system="synthetic",domain="clinical_trials",export_format="fhir",payload={"x":1})
    def test_rejects_changed_content_under_same_key(self):
        enqueue(self.db,source_system="synthetic",domain="hospital",export_format="fhir",payload={"x":1},idempotency_key="same")
        with self.assertRaisesRegex(ValueError,"manual review"):
            enqueue(self.db,source_system="synthetic",domain="hospital",export_format="fhir",payload={"x":2},idempotency_key="same")
    @patch("scripts.facility_spool.urlopen",return_value=Response())
    def test_replay_marks_only_accepted_export_sent(self,mock):
        enqueue(self.db,source_system="synthetic",domain="hospital",export_format="fhir",payload={"resourceType":"Bundle"})
        result=replay(self.db,api_base_url="https://jlight.example",token="synthetic-token",organization_id="synthetic-org")
        self.assertEqual(result,{"sent":1,"failed":0,"pending":0})
        req=mock.call_args.args[0]
        self.assertEqual(req.get_header("Idempotency-key"),self.db.execute("SELECT idempotency_key FROM spool").fetchone()[0])
        self.assertEqual(self.db.execute("SELECT status FROM spool").fetchone()[0],"sent")
    @patch("scripts.facility_spool.urlopen",side_effect=OSError("offline"))
    def test_offline_replay_preserves_pending_record(self,mock):
        enqueue(self.db,source_system="synthetic",domain="hospital",export_format="fhir",payload={"x":1})
        result=replay(self.db,api_base_url="https://jlight.example",token="synthetic-token",organization_id="synthetic-org")
        self.assertEqual(result["pending"],1)
        self.assertEqual(self.db.execute("SELECT status FROM spool").fetchone()[0],"pending")

if __name__=="__main__": unittest.main(verbosity=2)
