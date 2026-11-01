#!/usr/bin/env python3
"""Static release guards for high-risk Patient Journey and navigation regressions."""
from pathlib import Path
import re
import unittest

HTML = Path("index.html").read_text(encoding="utf-8")


class PatientJourneyReleaseGuards(unittest.TestCase):
    def test_quick_access_and_workspace_switch_are_removed(self):
        forbidden = (
            'jlight-launchpad',
            'jlight-quick-card',
            'Switch Workspace',
            'Switch workspace',
            'openWsModal',
            'closeWsModal',
            'doSwitchWorkspace',
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, HTML)

    def test_clinical_trials_uses_separate_participant_timeline(self):
        start = HTML.index("function buildPatientJourneyEvents(patient)")
        end = HTML.index("\nfunction selectJourneyPatient", start)
        function = HTML[start:end]
        self.assertNotIn("STATE.role==='Trial'", function)
        self.assertNotIn("STATE.participants", function)
        self.assertNotIn("STATE.visits", function)
        self.assertNotIn("STATE.adverseEvents", function)
        self.assertIn("async function renderTrialTimeline()", HTML)
        self.assertIn("key: 'trial-timeline'", HTML)
        self.assertIn('id="page-trial-timeline"', HTML)

    def test_patient_events_require_exact_patient_id_and_tenant(self):
        api = Path("jlight-backend/api/app.py").read_text(encoding="utf-8")
        self.assertIn("@app.route(\"/api/patient-journey/<uuid:patient_id>\"", api)
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", api)
        self.assertIn("patient_id=%s::uuid", api)
        self.assertIn("patient_link_verified=true", api)
        self.assertIn("source_record_id", api)

    def test_issue_resolution_is_source_recorded_and_not_inferred(self):
        self.assertIn("status: String(row.status || 'Recorded')", HTML)
        self.assertIn("Source systems remain authoritative", HTML)
        self.assertIn("A recommendation is not proof that a correction occurred.", HTML)
        self.assertIn("Clinical Trials is excluded from this routine Patient Journey", HTML)


    def test_patient_journey_ui_exposes_two_report_action_and_status(self):
        start = HTML.index("function renderJourney() {")
        end = HTML.index("function downloadJourneyJson", start)
        function = HTML[start:end]
        self.assertIn('onclick="generatePatientJourneyReports()"', function)
        self.assertIn('id="patient-journey-report-status"', function)

    def test_two_separate_patient_reports_share_correlation_id(self):
        start = HTML.index("async function generatePatientJourneyReports()")
        end = HTML.index("\nfunction renderDashboard()", start)
        function = HTML[start:end]
        self.assertIn("patient-journey-summary", function)
        self.assertIn("patient-data-quality-traceability", function)
        self.assertIn("journeyReport.correlationId = correlationId", function)
        self.assertIn("qualityReport.correlationId = correlationId", function)
        self.assertEqual(function.count("downloadJourneyJson("), 2)

    def test_patient_journey_includes_proposal_critical_action_and_bioinformatics_sources(self):
        api = Path("jlight-backend/api/app.py").read_text(encoding="utf-8")
        for source in ("jl_clinical_orders", "clinical_action_at", "result_received_at",
                       "jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"):
            with self.subTest(source=source):
                self.assertIn(source, api)

    def test_patient_identity_is_masked_without_hospital_read_permission(self):
        self.assertIn("STATE.patientJourneyAvailableDomains || []).includes('hospital')", HTML)
        self.assertIn("Identity details are restricted by your workspace permissions", HTML)
        self.assertIn("Patient record ' + (index + 1)", HTML)

    def test_obsolete_aggregate_traceability_export_is_removed(self):
        self.assertNotIn("function buildJourneyReport()", HTML)
        self.assertNotIn("async function generateJourneyReport()", HTML)
        self.assertNotIn("jlight-traceability-report-", HTML)


if __name__ == "__main__":
    unittest.main(verbosity=2)
