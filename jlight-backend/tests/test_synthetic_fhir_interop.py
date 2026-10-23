"""End-to-end adapter checks using a fully synthetic FHIR R4 Bundle fixture."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.source_adapters import parse_source_export


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_fhir_r4_bundle.json")


class SyntheticFhirInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as handle:
            cls.bundle = json.load(handle)

    def test_fixture_is_synthetic_bundle_with_no_clinical_result_values(self):
        self.assertEqual(self.bundle["resourceType"], "Bundle")
        self.assertEqual(len(self.bundle["entry"]), 4)
        for entry in self.bundle["entry"]:
            resource = entry["resource"]
            self.assertNotIn("valueQuantity", resource)
            self.assertNotIn("valueString", resource)
            self.assertNotIn("conclusion", resource)

    def test_fhir_status_metadata_maps_across_supported_domains(self):
        cases = [
            ("hospital", "Encounter", "admission_closed"),
            ("laboratory", "ServiceRequest", "order_received"),
            ("bioinformatics", "Task", "released"),
            ("laboratory", "DiagnosticReport", "released"),
        ]
        for domain, resource_type, expected_event in cases:
            with self.subTest(domain=domain, resource_type=resource_type):
                events = parse_source_export("fhir", self.bundle,
                                             source_system="synthetic-fixture",
                                             domain=domain)
                selected = [event for event in events
                            if event["source_record_id"].startswith(resource_type + "/")]
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["event_type"], expected_event)
                self.assertEqual(selected[0]["source_patient_ref"], "Patient/SYN-001")
                self.assertTrue(selected[0]["event_id"])
                self.assertTrue(selected[0]["observed_at"].endswith("Z"))

    def test_clinical_trials_are_rejected_by_fhir_adapter(self):
        with self.assertRaisesRegex(ValueError, "separate participant workflow"):
            parse_source_export("fhir", self.bundle,
                                source_system="synthetic-fixture",
                                domain="clinical_trials")


if __name__ == "__main__":
    unittest.main(verbosity=2)
