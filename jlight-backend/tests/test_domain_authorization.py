"""Synthetic-only regression tests for explicit domain authorisation."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, g, request
from api import source_workflow


class DomainAuthorisationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_patient_journey_requires_report_grant_for_all_three_domains(self):
        with self.app.test_request_context("/api/patient-journeys"):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_patient_journey_report(lambda: ("ok", 200))
            with patch.object(source_workflow, "_domain_permission",
                               side_effect=lambda domain, action: domain != "laboratory"):
                response, status = wrapped()
            self.assertEqual(status, 403)
            self.assertIn("not authorised", response.get_json()["error"])

    def test_patient_journey_allowed_only_when_every_domain_has_report_grant(self):
        with self.app.test_request_context("/api/patient-journeys"):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_patient_journey_report(lambda: ("ok", 200))
            with patch.object(source_workflow, "_domain_permission", return_value=True) as check:
                response, status = wrapped()
            self.assertEqual((response, status), ("ok", 200))
            self.assertEqual(check.call_count, 3)
            self.assertTrue(all(call.args[1] == "report" for call in check.call_args_list))

    def test_domain_scope_fails_closed_when_header_missing(self):
        with self.app.test_request_context("/api/workflow-timelines"):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_domain_scope("read")(lambda: ("ok", 200))
            response, status = wrapped()
            self.assertEqual(status, 400)
            self.assertIn("X-JLIGHT-Domain", response.get_json()["error"])

    def test_domain_scope_rejects_without_explicit_grant(self):
        with self.app.test_request_context("/api/workflow-timelines",
                                           headers={"X-JLIGHT-Domain": "laboratory"}):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_domain_scope("read")(lambda: ("ok", 200))
            with patch.object(source_workflow, "_domain_permission", return_value=False):
                response, status = wrapped()
            self.assertEqual(status, 403)
            self.assertIn("not authorised", response.get_json()["error"])

    def test_domain_scope_accepts_only_explicitly_granted_selected_domain(self):
        with self.app.test_request_context("/api/workflow-timelines",
                                           headers={"X-JLIGHT-Domain": "bioinformatics"}):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_domain_scope("read")(lambda: (g.jlight_domain, 200))
            with patch.object(source_workflow, "_domain_permission", return_value=True) as check:
                response, status = wrapped()
            self.assertEqual((response, status), ("bioinformatics", 200))
            check.assert_called_once_with("bioinformatics", "read")


    def test_cross_domain_patient_link_requires_all_three_write_grants(self):
        with self.app.test_request_context("/api/patient-links"):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_cross_domain_link_write(lambda: ("ok", 200))
            with patch.object(source_workflow, "_domain_permission",
                               side_effect=lambda domain, action: domain != "bioinformatics"):
                response, status = wrapped()
            self.assertEqual(status, 403)
            self.assertIn("not authorised", response.get_json()["error"])

    def test_cross_domain_patient_link_allowed_only_with_all_three_write_grants(self):
        with self.app.test_request_context("/api/patient-links"):
            g.jlight_actor = {"subject": "synthetic-user", "organization_id": "synthetic-org", "role": "admin"}
            wrapped = source_workflow.require_cross_domain_link_write(lambda: ("ok", 200))
            with patch.object(source_workflow, "_domain_permission", return_value=True) as check:
                response, status = wrapped()
            self.assertEqual((response, status), ("ok", 200))
            self.assertEqual(check.call_count, 3)
            self.assertTrue(all(call.args[1] == "write" for call in check.call_args_list)


if __name__ == "__main__":
    unittest.main()
