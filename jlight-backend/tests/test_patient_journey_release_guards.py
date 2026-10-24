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

    def test_trial_journey_returns_before_non_trial_sources_are_added(self):
        start = HTML.index("function buildPatientJourneyEvents(patient)")
        end = HTML.index("\nfunction selectJourneyPatient", start)
        function = HTML[start:end]
        trial_guard = function.index("if(STATE.role==='Trial')")
        trial_return = function.index("return events;", trial_guard)
        non_trial_add = function.index("add('Hospital'")
        self.assertLess(trial_guard, trial_return)
        self.assertLess(trial_return, non_trial_add)
        trial_block = function[trial_guard:trial_return]
        self.assertIn("STATE.participants", trial_block)
        self.assertIn("STATE.visits", trial_block)
        self.assertIn("STATE.adverseEvents", trial_block)
        self.assertNotIn("STATE.labOrders", trial_block)
        self.assertNotIn("STATE.bioRuns", trial_block)
        self.assertNotIn("STATE.cards", trial_block)

    def test_patient_events_require_exact_patient_id(self):
        start = HTML.index("function buildPatientJourneyEvents(patient)")
        end = HTML.index("\nfunction selectJourneyPatient", start)
        function = HTML[start:end]
        self.assertGreaterEqual(function.count("String(row.patientId)!==pid"), 2)

    def test_issue_resolution_is_not_inferred_from_recommendation(self):
        start = HTML.index("function buildPatientJourneyEvents(patient)")
        end = HTML.index("\nfunction selectJourneyPatient", start)
        function = HTML[start:end]
        self.assertIn("r.resolution?' · recorded resolution: '+r.resolution", function)
        self.assertIn("r.recommendation?' · recommended action: '+r.recommendation", function)


if __name__ == "__main__":
    unittest.main(verbosity=2)
