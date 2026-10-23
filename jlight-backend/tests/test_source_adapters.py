"""Synthetic-only tests for FHIR, CSV and HL7 status adapters."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.source_adapters import parse_source_export, parse_fhir_bundle, parse_csv_events, parse_hl7v2_status


class SourceAdapterTests(unittest.TestCase):
    def test_fhir_encounter_status_maps_without_patient_identity(self):
        bundle = {"resourceType":"Bundle","entry":[{"resource":{
            "resourceType":"Encounter","id":"enc-1","status":"in-progress",
            "meta":{"lastUpdated":"2026-10-23T08:00:00Z"},
            "subject":{"reference":"Patient/123"}
        }}]}
        events = parse_fhir_bundle(bundle, source_system="synthetic-his", domain="hospital")
        self.assertEqual(events[0]["event_type"], "work_started")
        self.assertIsNone(events[0]["jlight_patient_id"])
        self.assertFalse(events[0]["source_values_modified"])

    def test_csv_adapter_requires_timezone_and_explicit_columns(self):
        text = "source_record_id,event_type,observed_at\nORD-1,order_received,2026-10-23T08:00:00Z\n"
        self.assertEqual(parse_csv_events(text, source_system="synthetic-lis", domain="laboratory")[0]["event_type"], "order_received")
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            parse_csv_events("source_record_id,event_type,observed_at\nORD-1,order_received,2026-10-23T08:00:00\n",
                             source_system="synthetic-lis", domain="laboratory")

    def test_hl7_adapter_rejects_ambiguous_local_timestamp(self):
        msg = "MSH|^~\\&|SYS|FAC|JLIGHT|FAC|20261023080000||ORM^O01|MSG-1|P|2.5\rORC|NW|ORD-1||||SC"
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            parse_hl7v2_status(msg, source_system="synthetic-lis", domain="laboratory")

    def test_hl7_adapter_accepts_explicit_non_utc_offset(self):
        msg = "MSH|^~\\&|SYS|FAC|JLIGHT|FAC|20261023130000+0200||ORM^O01|MSG-2|P|2.5\rORC|NW|ORD-1|||SC"
        events = parse_hl7v2_status(msg, source_system="synthetic-lis", domain="laboratory")
        self.assertEqual(events[0]["observed_at"], "2026-10-23T11:00:00Z")
        self.assertEqual(events[0]["event_type"], "order_received")

    def test_clinical_trials_stays_separate(self):
        with self.assertRaisesRegex(ValueError, "separate participant workflow"):
            parse_source_export("csv", "source_record_id,event_type,observed_at\nA,order_received,2026-10-23T08:00:00Z",
                                source_system="synthetic", domain="clinical_trials")

    def test_unknown_format_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            parse_source_export("sql", {}, source_system="synthetic", domain="hospital")


if __name__ == "__main__":
    unittest.main(verbosity=2)
