import unittest

from engine.patient_journey_reconciliation import reconcile_patient_journeys


def rec(domain, kind, source_id, data, patient="JL-P-001", status="verified"):
    return {
        "domain": domain,
        "source_key": f"{domain}::{kind}::{source_id}",
        "jlight_patient_id": patient,
        "link_status": status,
        "data": data,
    }


class PatientJourneyReconciliationTests(unittest.TestCase):
    def test_exact_hospital_lab_sample_bioinformatics_graph_passes(self):
        records = [
            rec("hospital", "clinical_order", "H1", {"order_id": "ORD-1"}),
            rec("laboratory", "order", "ORD-1", {"order_id": "ORD-1"}),
            rec("laboratory", "sample", "S1", {"order_id": "ORD-1", "accession_id": "ACC-1"}),
            rec("bioinformatics", "accession", "A1", {"accession_id": "ACC-1"}),
            rec("bioinformatics", "run", "R1", {"accession_id": "ACC-1"}),
        ]
        result = reconcile_patient_journeys(records)
        journey = result["journeys"][0]
        self.assertEqual(result["complete_three_section_journeys"], 1)
        self.assertFalse(journey["review_required"])

    def test_multiple_orders_are_matched_individually_not_as_patient_wide_sets(self):
        records = [
            rec("hospital", "clinical_order", "H1", {"order_id": "ORD-1"}),
            rec("hospital", "clinical_order", "H2", {"order_id": "ORD-2"}),
            rec("laboratory", "order", "ORD-1", {"order_id": "ORD-1"}),
            rec("laboratory", "order", "ORD-2", {"order_id": "ORD-2"}),
            rec("laboratory", "sample", "S1", {"order_id": "ORD-1", "accession_id": "ACC-1"}),
            rec("laboratory", "sample", "S2", {"order_id": "ORD-2", "accession_id": "ACC-2"}),
            rec("bioinformatics", "accession", "A1", {"accession_id": "ACC-1"}),
            rec("bioinformatics", "accession", "A2", {"accession_id": "ACC-2"}),
        ]
        result = reconcile_patient_journeys(records)
        self.assertFalse(result["journeys"][0]["review_required"])

    def test_unmatched_exact_relationship_is_flagged(self):
        records = [
            rec("hospital", "clinical_order", "H1", {"order_id": "ORD-NOT-FOUND"}),
            rec("laboratory", "order", "ORD-1", {"order_id": "ORD-1"}),
            rec("laboratory", "sample", "S1", {"order_id": "ORD-1", "accession_id": "ACC-MISSING"}),
            rec("bioinformatics", "accession", "A1", {"accession_id": "ACC-1"}),
        ]
        codes = {f["code"] for f in reconcile_patient_journeys(records)["journeys"][0]["findings"]}
        self.assertIn("hospital_order_unmatched", codes)
        self.assertIn("sample_accession_unmatched", codes)

    def test_missing_references_are_incomplete_not_mismatch(self):
        records = [
            rec("hospital", "clinical_order", "H1", {}),
            rec("laboratory", "order", "ORD-1", {"order_id": "ORD-1"}),
            rec("laboratory", "sample", "S1", {}),
            rec("bioinformatics", "accession", "A1", {"accession_id": "ACC-1"}),
        ]
        codes = {f["code"] for f in reconcile_patient_journeys(records)["journeys"][0]["findings"]}
        self.assertIn("source_linkage_reference_missing", codes)
        self.assertNotIn("hospital_order_unmatched", codes)
        self.assertNotIn("sample_order_unmatched", codes)

    def test_unlinked_and_clinical_trials_are_excluded(self):
        records = [
            rec("hospital", "clinical_order", "H1", {"order_id": "ORD-1"}),
            rec("clinical_trials", "participant", "T1", {"participant_id": "TRIAL-1"}),
            rec("laboratory", "sample", "S2", {}, patient=None, status="unlinked"),
        ]
        result = reconcile_patient_journeys(records)
        self.assertEqual(result["excluded_records"]["clinical_trials"], 1)
        self.assertEqual(result["excluded_records"]["unlinked"], 1)
        self.assertFalse(result["clinical_trials_included"])


if __name__ == "__main__":
    unittest.main()
