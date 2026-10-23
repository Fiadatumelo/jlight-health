"""Synthetic-only tests for explainable operational Decision Cards."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.decision_cards import build_decision_cards


class DecisionCardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
        self.events = [
            {"event_id":"EV-1","source_system":"synthetic-his","source_record_id":"ENC-1",
             "domain":"hospital","event_type":"admission_opened","observed_at":"2026-10-23T08:00:00Z"},
            {"event_id":"EV-2","source_system":"synthetic-lis","source_record_id":"ORD-1",
             "domain":"laboratory","event_type":"work_started","observed_at":"2026-10-23T11:30:00Z"},
        ]

    def test_stalled_workflow_card_has_traceable_evidence(self):
        cards = build_decision_cards(self.events, now=self.now, stall_after_minutes=120)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["domain"], "hospital")
        self.assertEqual(cards[0]["state"], "ATTENTION")
        self.assertEqual(cards[0]["evidence"][0]["event_ids"], ["EV-1"])
        self.assertTrue(cards[0]["human_review_required"])
        self.assertFalse(cards[0]["source_values_modified"])

    def test_terminal_event_does_not_trigger_stall_card(self):
        events = [{**self.events[0], "event_type":"admission_closed"}]
        self.assertEqual(build_decision_cards(events, now=self.now, stall_after_minutes=60), [])

    def test_recent_event_does_not_trigger_stall_card(self):
        self.assertEqual(build_decision_cards([self.events[1]], now=self.now, stall_after_minutes=60), [])

    def test_clinical_trials_rejected(self):
        with self.assertRaisesRegex(ValueError, "separate"):
            build_decision_cards([{**self.events[0], "domain":"clinical_trials"}], now=self.now)

    def test_invalid_threshold_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            build_decision_cards(self.events, now=self.now, stall_after_minutes=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
