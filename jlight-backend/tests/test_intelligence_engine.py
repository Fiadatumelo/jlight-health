"""Focused tests for JLIGHT's evidence-first Intelligence Engine."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.intelligence_engine import build_intelligence_summary


class IntelligenceEngineTests(unittest.TestCase):
    def test_reuses_existing_csv_qc_metrics(self):
        result = build_intelligence_summary(csv_analysis={
            "severity": "crit", "riskScore": 84,
            "summary": "contains text that must not be copied",
            "filename": "patient_name_sensitive.csv",
            "ml": {"anomaly_count": 2, "westgard_violations": ["1_3s"]},
        })
        self.assertEqual(result["overall_status"], "review_required")
        finding = result["findings"][0]
        self.assertEqual(finding["source"], "laboratory")
        self.assertEqual(finding["evidence"]["anomaly_count"], 2)
        self.assertNotIn("patient_name_sensitive.csv", str(result))
        self.assertNotIn("contains text that must not be copied", str(result))

    def test_bioinformatics_qc_pass_is_not_clinical_validation(self):
        result = build_intelligence_summary(bioinformatics={
            "qc_status": "PASS", "flags": [], "sequence": "ATCGATCG",
            "interpretation": "sensitive free text",
        })
        self.assertEqual(result["findings"][0]["status"], "pass")
        self.assertIn("not clinical validation", result["findings"][0]["recommended_next_step"])
        self.assertNotIn("ATCGATCG", str(result))
        self.assertNotIn("sensitive free text", str(result))

    def test_missing_inputs_are_insufficient_not_normal(self):
        result = build_intelligence_summary()
        self.assertEqual(result["overall_status"], "insufficient_input")
        self.assertEqual(result["finding_count"], 0)
        self.assertFalse(result["human_review_required"])

    def test_unknown_bioinformatics_qc_requires_review(self):
        result = build_intelligence_summary(bioinformatics={"qc_status": "not-sure"})
        self.assertEqual(result["findings"][0]["status"], "unknown")
        self.assertTrue(result["human_review_required"])

    def test_bioinformatics_failure_is_normalized(self):
        result = build_intelligence_summary(bioinformatics={"qc_status": "FAIL", "flags": []})
        self.assertEqual(result["findings"][0]["status"], "review")
        self.assertEqual(result["findings"][0]["severity"], "high")
        self.assertTrue(result["human_review_required"])

    def test_accepts_only_allowlisted_journey_metadata(self):
        result = build_intelligence_summary(journey_checks=[
            {"check_id": "missing_lab_result", "source": "laboratory", "status": "review",
             "severity": "high", "evidence_count": 1, "patient_name": "Jane Doe"},
            {"check_id": "bad check id!", "source": "hospital", "status": "fail"},
            {"check_id": "trial_cross_leak", "source": "clinical_trials", "status": "fail"},
        ])
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["finding_id"], "journey_missing_lab_result")
        self.assertNotIn("Jane Doe", str(result))
        self.assertNotIn("trial_cross_leak", str(result))

    def test_invalid_numeric_values_are_bounded_safely(self):
        result = build_intelligence_summary(csv_analysis={
            "severity": "att", "riskScore": "999999", "ml": {"anomaly_count": "bad"}
        })
        evidence = result["findings"][0]["evidence"]
        self.assertEqual(evidence["risk_score"], 100)
        self.assertEqual(evidence["anomaly_count"], 0)

    def test_no_claim_of_diagnosis_or_causation(self):
        result = build_intelligence_summary(
            csv_analysis={"severity": "crit", "riskScore": 80},
            bioinformatics={"qc_status": "FAIL", "flags": ["raw string ignored"]},
        )
        self.assertTrue(all(item["requires_human_review"] for item in result["findings"]))
        self.assertTrue(any("not proof" in limitation for limitation in result["limitations"]))

    def test_high_severity_requires_review_even_when_status_is_pass(self):
        result = build_intelligence_summary(journey_checks=[
            {"check_id": "missing_lab_result", "source": "laboratory",
             "status": "pass", "severity": "high", "evidence_count": 1},
        ])
        self.assertEqual(result["findings"][0]["status"], "pass")
        self.assertTrue(result["findings"][0]["requires_human_review"])
        self.assertEqual(result["overall_status"], "review_required")
        self.assertTrue(result["human_review_required"])


if __name__ == "__main__":
    unittest.main()
