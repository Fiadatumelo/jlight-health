import unittest

from engine.patient_journey_reconciliation import reconcile_patient_journeys


def rec(domain, source_id, data, patient="JL-P-001", status="verified"):
    return {
        "domain": domain,
        "source_key": f"{domain}::{source_id}",
        "source_record_id": source_id,
        "jlight_patient_id": patient,
        "link_status": status,
        "data": data,
    }


class PatientJourneyReconciliationTests(unittest.TestCase):
    def test_tracks_one_patient_across_all_three_sections(self):
        records = [
            rec("hospital", "H-1", {"encounter_id": "ENC-1", "order_id": "ORD-1"}),
            rec("laboratory", "L-1", {"encounter_id": "ENC-1", "order_id": "ORD-1", "specimen_id": "SP-1"}),
            rec("bioinformatics", "B-1", {"specimen_id": "SP-1", "accession_id": "ACC-1"}),
        ]
        result = reconcile_patient_journeys(records)
        self.assertEqual(result["journey_count"], 1)
        self.assertEqual(result["complete_three_section_journeys"], 1)
        self.assertEqual(result["journeys"][0]["domains_present"], ["bioinformatics", "hospital", "laboratory"])
        self.assertFalse(result["journeys"][0]["review_required"])

    def test_flags_cross_system_order_and_specimen_conflicts(self):
        records = [
            rec("hospital", "H-1", {"order_id": "ORD-1", "encounter_id": "ENC-1"}),
            rec("laboratory", "L-1", {"order_id": "ORD-2", "specimen_id": "SP-1"}),
            rec("bioinformatics", "B-1", {"specimen_id": "SP-9", "accession_id": "ACC-1"}),
        ]
        result = reconcile_patient_journeys(records)
        codes = {f["code"] for f in result["journeys"][0]["findings"]}
        self.assertIn("cross_system_identifier_conflict", codes)
        self.assertEqual(result["journeys_requiring_review"], 1)

    def test_missing_section_unlinked_and_trials_are_separated(self):
        records = [
            rec("hospital", "H-1", {"encounter_id": "ENC-1"}),
            rec("laboratory", "L-1", {}, patient=None, status="unlinked"),
            rec("clinical_trials", "T-1", {"participant_id": "TRIAL-1"}),
        ]
        result = reconcile_patient_journeys(records)
        self.assertEqual(result["complete_three_section_journeys"], 0)
        self.assertIn("journey_section_missing", result["finding_counts"])
        self.assertEqual(result["excluded_records"]["unlinked"], 1)
        self.assertEqual(result["excluded_records"]["clinical_trials"], 1)
        self.assertFalse(result["clinical_trials_included"])

    def test_multiple_valid_orders_do_not_create_patient_wide_false_mismatch(self):
        records = [
            rec("hospital", "H-1", {"order_id": "ORD-1"}),
            rec("hospital", "H-2", {"order_id": "ORD-2"}),
            rec("laboratory", "L-1", {"order_id": "ORD-1"}),
            rec("laboratory", "L-2", {"order_id": "ORD-2"}),
            rec("bioinformatics", "B-1", {"accession_id": "ACC-1"}),
        ]
        result = reconcile_patient_journeys(records)
        codes = {f["code"] for f in result["journeys"][0]["findings"]}
        self.assertNotIn("cross_system_identifier_conflict", codes)

    def test_missing_references_are_incomplete_not_mismatch(self):
        records = [
            rec("hospital", "H-1", {"encounter_id": "ENC-1"}),
            rec("laboratory", "L-1", {"result": "positive"}),
            rec("bioinformatics", "B-1", {"lineage": "example"}),
        ]
        result = reconcile_patient_journeys(records)
        codes = [f["code"] for f in result["journeys"][0]["findings"]]
        self.assertEqual(codes.count("source_linkage_reference_missing"), 2)
        self.assertNotIn("cross_system_identifier_conflict", codes)


if __name__ == "__main__":
    unittest.main()
