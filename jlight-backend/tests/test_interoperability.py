"""Synthetic-only tests for JLIGHT's interoperability and resilience foundation."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.interoperability import (
    build_patient_journeys,
    classify_sync_change,
    evaluate_source_health,
    normalize_record,
    parse_hl7_v25_message,
)

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)


def record(source, source_id, domain, patient_id, updated="2026-10-23T08:30:00Z", data=None):
    return {
        "source_system": source,
        "source_record_id": source_id,
        "domain": domain,
        "record_type": "synthetic_test_record",
        "source_updated_at": updated,
        "jlight_patient_id": patient_id,
        "data": data or {"synthetic": True, "status": "test-only"},
    }


class InteroperabilityFoundationTests(unittest.TestCase):
    def test_synthetic_cross_section_journey_uses_verified_id(self):
        items = [
            normalize_record(record("synthetic-his", "H-001", "hospital", "JL-SYN-001"), now=NOW),
            normalize_record(record("synthetic-lis", "L-001", "laboratory", "JL-SYN-001"), now=NOW),
            normalize_record(record("synthetic-bio", "B-001", "bioinformatics", "JL-SYN-001"), now=NOW),
        ]
        result = build_patient_journeys(items)
        self.assertEqual(len(result["journeys"]), 1)
        self.assertTrue(result["journeys"][0]["cross_section"])
        self.assertEqual(result["journeys"][0]["domains_present"], ["bioinformatics", "hospital", "laboratory"])
        self.assertEqual(result["unlinked_records"], [])

    def test_never_links_by_name_or_demographics(self):
        item = normalize_record(record("synthetic-his", "H-002", "hospital", None), now=NOW)
        result = build_patient_journeys([item])
        self.assertEqual(result["journeys"], [])
        self.assertEqual(result["unlinked_records"][0]["reason"], "verified_patient_link_required")

    def test_clinical_trials_are_separate(self):
        trial = record("synthetic-ctms", "T-001", "clinical_trials", "SHOULD-NOT-LINK")
        trial["trial_participant_id"] = "TRIAL-P-001"
        item = normalize_record(trial, now=NOW)
        result = build_patient_journeys([item])
        self.assertEqual(result["journeys"], [])
        self.assertEqual(len(result["clinical_trial_records_separate"]), 1)
        self.assertIsNone(item["jlight_patient_id"])

    def test_duplicate_source_record_is_reported(self):
        item = normalize_record(record("synthetic-lis", "L-003", "laboratory", "JL-SYN-003"), now=NOW)
        result = build_patient_journeys([item, item])
        self.assertEqual(result["duplicate_source_keys"], ["synthetic-lis::L-003"])

    def test_stale_record_is_marked_not_hidden(self):
        item = normalize_record(
            record("synthetic-his", "H-004", "hospital", "JL-SYN-004", updated="2026-10-20T08:00:00Z"),
            now=NOW,
            stale_after_hours=24,
        )
        self.assertEqual(item["freshness"], "stale")
        self.assertFalse(item["provenance"]["source_values_modified"])

    def test_unavailable_source_never_claims_current_data(self):
        result = evaluate_source_health(
            connection_state="unavailable",
            last_successful_sync_at="2026-10-23T08:55:00Z",
            now=NOW,
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["usable_as_current"])

    def test_old_sync_is_stale_even_if_connection_says_connected(self):
        result = evaluate_source_health(
            connection_state="connected",
            last_successful_sync_at="2026-10-23T07:00:00Z",
            now=NOW,
            stale_after_minutes=60,
        )
        self.assertEqual(result["status"], "stale")
        self.assertFalse(result["usable_as_current"])

    def test_same_timestamp_payload_conflict_is_held_for_review(self):
        old = normalize_record(record("synthetic-lis", "L-009", "laboratory", "JL-SYN-009"), now=NOW)
        changed_raw = record("synthetic-lis", "L-009", "laboratory", "JL-SYN-009", data={"synthetic": True, "status": "changed"})
        changed = normalize_record(changed_raw, now=NOW)
        result = classify_sync_change(old, changed)
        self.assertEqual(result["action"], "conflict_hold")
        self.assertTrue(result["requires_review"])

    def test_newer_source_version_is_candidate_not_silent_overwrite(self):
        old = normalize_record(record("synthetic-lis", "L-010", "laboratory", "JL-SYN-010", updated="2026-10-23T07:00:00Z"), now=NOW)
        new = normalize_record(record("synthetic-lis", "L-010", "laboratory", "JL-SYN-010", updated="2026-10-23T08:00:00Z", data={"synthetic": True, "status": "updated"}), now=NOW)
        result = classify_sync_change(old, new)
        self.assertEqual(result["action"], "version_candidate")
        self.assertTrue(result["requires_review"])

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_record(record("synthetic-his", "H-011", "hospital", "JL-SYN-011", updated="2026-10-23T08:30:00"), now=NOW)


    def test_hl7_adt_message_becomes_unlinked_hospital_event(self):
        message = (
            "MSH|^~\\\\&|SYNTH-HIS|FAC|JLIGHT|JLIGHT|20261101100000+0200||ADT^A01|MSG-ADT-1|P|2.5\\r"
            "PID|1||MRN-SYN-001^^^FAC^MR||Synthetic^Person\\r"
            "PV1|1|I|WARD^01^01"
        )
        parsed = parse_hl7_v25_message(message, source_system="synthetic-his")
        self.assertEqual(parsed["domain"], "hospital")
        self.assertEqual(parsed["events"][0]["event_type"], "admission")
        self.assertFalse(parsed["events"][0]["patient_link_verified"])
        self.assertIsNone(parsed["events"][0]["jlight_patient_id"])
        self.assertEqual(parsed["patient_link_status"], "unlinked_pending_governed_reconciliation")
        self.assertNotIn("MRN-SYN-001", str(parsed))
        self.assertEqual(len(parsed["events"][0]["source_patient_ref_hash"]), 64)

    def test_hl7_orm_message_becomes_laboratory_order_event(self):
        message = (
            "MSH|^~\\\\&|SYNTH-LIS|FAC|JLIGHT|JLIGHT|20261101100000+0200||ORM^O01|MSG-ORM-1|P|2.5\\r"
            "PID|1||MRN-SYN-002^^^FAC^MR\\r"
            "ORC|NW|ORD-001||PLACER-1|SC\\r"
            "OBR|1|ORD-001||718-7^Haemoglobin^LN"
        )
        parsed = parse_hl7_v25_message(message, source_system="synthetic-lis")
        self.assertEqual(parsed["domain"], "laboratory")
        self.assertEqual(parsed["events"][0]["event_type"], "laboratory_order")
        self.assertEqual(parsed["events"][0]["source_record_id"], "ORD-001")
        self.assertFalse(parsed["events"][0]["patient_link_verified"])

    def test_hl7_oru_message_becomes_result_event_without_patient_identity(self):
        message = (
            "MSH|^~\\\\&|SYNTH-LIS|FAC|JLIGHT|JLIGHT|20261101100000+0200||ORU^R01|MSG-ORU-1|P|2.5\\r"
            "PID|1||MRN-SYN-003^^^FAC^MR\\r"
            "OBR|1|ORD-002||718-7^Haemoglobin^LN\\r"
            "OBX|1|NM|718-7^Haemoglobin^LN||12.5|g/dL|||N|||F|||20261101100000+0200"
        )
        parsed = parse_hl7_v25_message(message, source_system="synthetic-lis")
        self.assertEqual(parsed["events"][0]["event_type"], "laboratory_result")
        self.assertEqual(parsed["events"][0]["domain"], "laboratory")
        self.assertFalse(parsed["events"][0]["patient_link_verified"])
        self.assertNotIn("12.5", str(parsed))

    def test_hl7_parser_rejects_timezone_free_timestamps(self):
        message = (
            "MSH|^~\\\\&|SYNTH-HIS|FAC|JLIGHT|JLIGHT|20261101100000||ADT^A01|MSG-ADT-2|P|2.5\\r"
            "PID|1||MRN-SYN-004^^^FAC^MR"
        )
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            parse_hl7_v25_message(message, source_system="synthetic-his")

    def test_hl7_parser_rejects_unsupported_message_types(self):
        message = (
            "MSH|^~\\\\&|SYNTH|FAC|JLIGHT|JLIGHT|20261101100000+0200||SIU^S12|MSG-SIU-1|P|2.5\\r"
            "PID|1||MRN-SYN-005^^^FAC^MR"
        )
        with self.assertRaisesRegex(ValueError, "Unsupported HL7 message type"):
            parse_hl7_v25_message(message, source_system="synthetic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
