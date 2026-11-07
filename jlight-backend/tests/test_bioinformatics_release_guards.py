"""Release guards for the unified JLIGHT Bioinformatics/Patient Journey baseline.

Tests assert current behaviour and trust boundaries rather than obsolete
frontend helper names from the pre-reconciliation implementation.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
API = (ROOT / "jlight-backend" / "api" / "app.py").read_text(encoding="utf-8")
PIPELINE = (ROOT / "bioinformatics" / "tb_pipeline.py").read_text(encoding="utf-8")


def function_source(source, signature):
    start = source.index(signature)
    ends = [
        p for p in (
            source.find("\nfunction ", start + len(signature)),
            source.find("\nasync function ", start + len(signature)),
            source.find("\ndef ", start + len(signature)),
        ) if p >= 0
    ]
    return source[start:min(ends)] if ends else source[start:]


class BioinformaticsReleaseGuards(unittest.TestCase):
    def test_patient_journey_uses_current_two_report_workflow(self):
        render = function_source(HTML, "function renderJourney()")
        reports = function_source(HTML, "async function generatePatientJourneyReports()")
        self.assertIn('onclick="generatePatientJourneyReports()"', render)
        self.assertIn('id="patient-journey-report-status"', render)
        self.assertIn("reportType: 'patient-journey-summary'", reports)
        self.assertIn("reportType: 'patient-data-quality-traceability'", reports)
        self.assertEqual(reports.count("downloadJourneyJson("), 2)
        self.assertIn("if (!events.length)", reports)
        self.assertIn("No reports have been generated", reports)

    def test_patient_journey_exports_only_summary_fields_not_sequence_payloads(self):
        reports = function_source(HTML, "async function generatePatientJourneyReports()")
        self.assertIn("buildPatientJourneyEvents(patient)", reports)
        self.assertNotIn("fastq", reports.lower())
        self.assertNotIn("sequence_payload", reports.lower())
        self.assertNotIn("vcf_content", reports.lower())
        self.assertNotIn("patientId:", reports)
        self.assertIn("sourceRecordId: e.sourceRecordId || null", reports)

    def test_bioinformatics_analysis_report_is_available_in_bioinformatics_workspace(self):
        render = function_source(HTML, "function renderBioinformaticsTB()")
        report = function_source(HTML, "function generateTBProfilerGenomicReport(")
        self.assertIn("generateTBProfilerGenomicReport()", render)
        self.assertIn("Generate full report", render)
        self.assertIn("TB GENOMIC DRUG-RESISTANCE REPORT", report)
        self.assertIn("Genotypic predictions are not phenotypic DST", report)
        self.assertIn("no-call results are not evidence of susceptibility", report)
        self.assertIn("No patient details or nucleotide sequences are included", report)
        self.assertIn("Only drugs explicitly named in source annotations are listed", report)

    def test_bioinformatics_report_does_not_claim_unavailable_drug_panel(self):
        report = function_source(HTML, "function generateTBProfilerGenomicReport(")
        self.assertIn("complete evaluated drug panel", report)
        self.assertIn("Absence of a drug or mutation is not proof of susceptibility", report)
        self.assertIn("confirm by phenotypic DST", report)

    def test_pipeline_runs_required_tools_and_records_provenance(self):
        for token in (
            '"fastqc": version(["fastqc", "--version"])',
            '"multiqc": version(["multiqc", "--version"])',
            '"tb-profiler": version(["tb-profiler", "--version"])',
            "sha256(p)",
            '"run-manifest.json"',
            '"completed_pending_expert_review"',
            '"UNPINNED: exact mutation database commit was not supplied"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, PIPELINE)

    def test_pipeline_enforces_private_storage_and_fastq_pair_validation(self):
        self.assertIn("JLIGHT_PRIVATE_DATA_ROOT", PIPELINE)
        self.assertIn("validate_private_path", PIPELINE)
        self.assertIn("validate_paired_fastq(args.r1, args.r2)", PIPELINE)
        self.assertIn("Paired FASTQ files contain different record counts", PIPELINE)
        self.assertIn("Paired FASTQ read names are out of sync", PIPELINE)

    def test_failed_pipeline_stage_is_not_reported_as_negative_result(self):
        self.assertIn("QC failure or pipeline failure must not be interpreted as a negative result.", PIPELINE)
        self.assertIn('manifest["status"] = "failed"', PIPELINE)
        self.assertIn('"status": "failed"', PIPELINE)
        self.assertIn("class StageFailure", PIPELINE)

    def test_patient_journey_api_is_exact_patient_and_tenant_scoped(self):
        journey = function_source(API, "def api_patient_journey(")
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", journey)
        self.assertIn("WHERE org_id=%s::uuid AND patient_id=%s::uuid", journey)
        self.assertIn("Clinical Trials is deliberately excluded", journey)
        self.assertIn('"bioinformatics" in domains', journey)
        self.assertIn("jl_bio_runs", journey)
        self.assertIn("jl_bio_qc", journey)
        self.assertIn("jl_bio_amr", journey)

    def test_trial_workspace_is_not_in_shared_patient_journey_authorisation(self):
        auth = function_source(API, "def _patient_journey_authorisation(")
        self.assertIn('("hospital", "laboratory", "bioinformatics")', auth)
        self.assertNotIn('"trial"', auth.lower())
        self.assertNotIn('"clinical_trials"', auth.lower())

    def test_patient_journey_does_not_use_legacy_trial_participant_state(self):
        journey = function_source(HTML, "function buildPatientJourneyEvents(patient)")
        self.assertNotIn("STATE.participants", journey)
        self.assertNotIn("STATE.visits", journey)
        self.assertNotIn("STATE.adverseEvents", journey)


if __name__ == "__main__":
    unittest.main(verbosity=2)
