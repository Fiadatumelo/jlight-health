from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
PIPELINE = (ROOT / "bioinformatics" / "tb_pipeline.py").read_text(encoding="utf-8")

class BioinformaticsReleaseGuards(unittest.TestCase):
    def test_patient_journey_report_action_is_present(self):
        self.assertIn("generateSelectedPatientJourneyReport()", HTML)
        self.assertIn("function generateSelectedPatientJourneyReport()", HTML)
        self.assertIn("JLIGHT Patient Journey Report", HTML)

    def test_printable_report_helper_is_present(self):
        self.assertIn("function openPrintableReport(", HTML)
        self.assertIn("Print / Save as PDF", HTML)

    def test_patient_journey_report_excludes_raw_sequence_payloads(self):
        start = HTML.index("function generateSelectedPatientJourneyReport()")
        end = HTML.index("\nfunction renderDashboard()", start)
        report = HTML[start:end]
        self.assertIn("Raw sequence reads, sequence files and unrestricted variant files are excluded.", report)
        self.assertIn("buildPatientJourneyEvents(patient)", report)

    def test_tb_runner_uses_real_external_tools_and_provenance(self):
        for token in ("fastqc", "multiqc", "tb-profiler", "sha256", "run-manifest.json", "completed_pending_expert_review"):
            with self.subTest(token=token):
                self.assertIn(token, PIPELINE)

    def test_failed_run_is_not_a_negative_result(self):
        self.assertIn("QC failure or pipeline failure must not be interpreted as a negative result.", PIPELINE)
        self.assertIn('manifest["status"] = "failed"', PIPELINE)

if __name__ == "__main__":
    unittest.main(verbosity=2)
