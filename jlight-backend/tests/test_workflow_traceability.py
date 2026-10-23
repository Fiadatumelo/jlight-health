"""Synthetic-only tests for read-only workflow traceability."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.workflow_traceability import build_workflow_timelines, build_patient_journeys, normalize_workflow_event


def event(event_id, event_type, observed_at, patient_id="JL-SYN-001", domain="laboratory"):
    return {
        "event_id": event_id,
        "source_system": "synthetic-lis",
        "source_record_id": "ORD-SYN-001",
        "domain": domain,
        "event_type": event_type,
        "observed_at": observed_at,
        "jlight_patient_id": patient_id,
        "source_status": event_type,
    }


class WorkflowTraceabilityTests(unittest.TestCase):
    def test_orders_source_events_into_read_only_timeline(self):
        later = normalize_workflow_event(event("EV-2", "released", "2026-10-23T10:00:00Z"))
        earlier = normalize_workflow_event(event("EV-1", "order_received", "2026-10-23T09:00:00Z"))
        result = build_workflow_timelines([later, earlier])
        timeline = result["timelines"][0]
        self.assertEqual([item["event_id"] for item in timeline["events"]], ["EV-1", "EV-2"])
        self.assertEqual(timeline["latest_event_type"], "released")
        self.assertTrue(timeline["terminal_event_observed"])
        self.assertTrue(result["source_system_remains_authoritative"])
        self.assertTrue(all(item["source_values_modified"] is False for item in timeline["events"]))

    def test_unlinked_event_is_not_assigned_to_a_patient(self):
        item = normalize_workflow_event(event("EV-3", "work_started", "2026-10-23T09:00:00Z", patient_id=None))
        result = build_workflow_timelines([item])
        self.assertEqual(result["timelines"][0]["patient_link_status"], "unlinked_or_inconsistent")
        self.assertEqual(result["unlinked_event_ids"], ["EV-3"])

    def test_inconsistent_patient_links_are_flagged(self):
        first = normalize_workflow_event(event("EV-4", "order_received", "2026-10-23T09:00:00Z", "JL-SYN-001"))
        second_raw = event("EV-5", "released", "2026-10-23T10:00:00Z", "JL-SYN-002")
        second = normalize_workflow_event(second_raw)
        result = build_workflow_timelines([first, second])
        self.assertEqual(result["timelines"][0]["patient_link_status"], "unlinked_or_inconsistent")

    def test_verified_events_form_one_cross_domain_patient_journey(self):
        events = [
            {"event_id":"EV-H","source_system":"synthetic-his","source_record_id":"ENC-1",
             "domain":"hospital","event_type":"admission_opened","observed_at":"2026-10-23T08:00:00Z",
             "jlight_patient_id":"00000000-0000-4000-8000-000000000001","patient_link_verified":True},
            {"event_id":"EV-L","source_system":"synthetic-lis","source_record_id":"ORD-1",
             "domain":"laboratory","event_type":"released","observed_at":"2026-10-23T09:00:00Z",
             "jlight_patient_id":"00000000-0000-4000-8000-000000000001","patient_link_verified":True},
            {"event_id":"EV-B","source_system":"synthetic-bio","source_record_id":"BIO-1",
             "domain":"bioinformatics","event_type":"analysis_completed","observed_at":"2026-10-23T10:00:00Z",
             "jlight_patient_id":"00000000-0000-4000-8000-000000000001","patient_link_verified":True},
        ]
        result = build_patient_journeys(events)
        self.assertEqual(len(result["journeys"]), 1)
        journey = result["journeys"][0]
        self.assertEqual(journey["domains_seen"], ["bioinformatics", "hospital", "laboratory"])
        self.assertTrue(journey["cross_domain"])
        self.assertEqual([e["event_id"] for e in journey["events"]], ["EV-H", "EV-L", "EV-B"])

    def test_unverified_events_never_enter_patient_journey(self):
        event = {"event_id":"EV-U","source_system":"synthetic-lis","source_record_id":"ORD-2",
                 "domain":"laboratory","event_type":"work_started","observed_at":"2026-10-23T09:00:00Z",
                 "jlight_patient_id":"00000000-0000-4000-8000-000000000001","patient_link_verified":False}
        result = build_patient_journeys([event])
        self.assertEqual(result["journeys"], [])
        self.assertEqual(result["unlinked_event_ids"], ["EV-U"])

    def test_clinical_trials_stay_separate(self):
        with self.assertRaisesRegex(ValueError, "separate participant workflow"):
            normalize_workflow_event(event("EV-6", "order_received", "2026-10-23T09:00:00Z", domain="clinical_trials"))

    def test_rejects_naive_timestamps_and_unsupported_events(self):
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            normalize_workflow_event(event("EV-7", "order_received", "2026-10-23T09:00:00"))
        with self.assertRaisesRegex(ValueError, "unsupported observed event type"):
            normalize_workflow_event(event("EV-8", "manual_result_entry", "2026-10-23T09:00:00Z"))

    def test_duplicate_event_ids_are_reported_not_counted_twice(self):
        item = normalize_workflow_event(event("EV-9", "order_received", "2026-10-23T09:00:00Z"))
        result = build_workflow_timelines([item, item])
        self.assertEqual(len(result["timelines"][0]["events"]), 1)
        self.assertEqual(result["duplicate_event_ids"], ["EV-9"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
