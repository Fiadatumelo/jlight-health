"""Tests for the authenticated workflow API fail-closed behavior."""
import unittest
from unittest.mock import patch

from flask import Flask
from api.source_workflow import source_workflow_bp


class SourceWorkflowAuthTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(source_workflow_bp)
        self.client = app.test_client()

    def test_source_record_requires_bearer_token(self):
        response = self.client.post("/api/source-records", json={})
        self.assertEqual(response.status_code, 401)

    def test_workflow_event_requires_bearer_token(self):
        response = self.client.post("/api/workflow-events", json={})
        self.assertEqual(response.status_code, 401)

    def test_timeline_requires_bearer_token(self):
        response = self.client.get("/api/workflow-timelines")
        self.assertEqual(response.status_code, 401)

    @patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_JWT_SECRET": ""}, clear=False)
    def test_auth_missing_configuration_fails_closed(self):
        response = self.client.get("/api/workflow-timelines",
                                   headers={"Authorization": "Bearer not-a-token",
                                            "X-JLIGHT-Organization": "00000000-0000-4000-8000-000000000001"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
