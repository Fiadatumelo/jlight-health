"""Verify the published South African TBProfiler reference outputs used by JLIGHT."""
import csv
import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "public_tbprofiler_bioruns.csv"


class PublishedTBProfilerReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIXTURE.open(newline="", encoding="utf-8") as handle:
            cls.rows = list(csv.DictReader(handle))
        cls.by_run = {row["sourceRecordId"]: row for row in cls.rows}

    def test_two_public_south_african_run_summaries_are_present(self):
        self.assertEqual(set(self.by_run), {"ERR10610053", "ERR10610083"})
        self.assertEqual(len(self.rows), 2)

    def test_high_coverage_pre_xdr_reference_preserves_variant_evidence(self):
        row = self.by_run["ERR10610053"]
        summary = json.loads(row["summary"])
        self.assertEqual(row["qualityStatus"], "qc_reported")
        self.assertEqual(summary["datasetAccession"], "PRJEB57919")
        self.assertEqual(summary["drugResistanceCall"], "Pre-XDR-TB")
        self.assertEqual(summary["medianCoverage"], 48)
        self.assertEqual(summary["percentReadsMapped"], 99.38)
        self.assertEqual(summary["numberOfReads"], 1752914)
        self.assertEqual(summary["resistanceAssociatedVariantCount"], 11)
        variants = {v["gene"]: v for v in summary["resistanceAssociatedVariants"]}
        self.assertEqual(variants["rpoB"]["mutation"], "p.Asp435Val")
        self.assertIn("rifampicin", variants["rpoB"]["drugs"])
        self.assertEqual(variants["rpoB"]["confidence"], "Assoc w R")
        self.assertEqual(variants["rpoB"]["estimatedFraction"], 0.96)

    def test_low_coverage_sensitive_call_is_not_misrepresented_as_definitive(self):
        row = self.by_run["ERR10610083"]
        summary = json.loads(row["summary"])
        self.assertEqual(row["qualityStatus"], "review_required_low_coverage")
        self.assertEqual(summary["drugResistanceCall"], "Sensitive")
        self.assertEqual(summary["medianCoverage"], 12)
        self.assertEqual(summary["percentReadsMapped"], 99.33)
        self.assertEqual(summary["numberOfReads"], 471201)
        self.assertEqual(summary["resistanceAssociatedVariantCount"], 0)
        self.assertTrue(any("below the recommended 30x" in x for x in summary["qcWarnings"]))

    def test_source_provenance_is_retained_and_patient_identity_is_absent(self):
        for run_id, row in self.by_run.items():
            summary = json.loads(row["summary"])
            self.assertEqual(summary["runAccession"], run_id)
            self.assertTrue(summary["sourceUrl"].startswith("https://tbdr.lshtm.ac.uk/results/"))
            self.assertEqual(summary["pipelineVersion"], "not_reported_by_public_results_page")
            self.assertEqual(summary["databaseVersion"], "not_reported_by_public_results_page")
            self.assertNotIn("patientId", summary)
            self.assertNotIn("patient_id", summary)
            self.assertNotIn("participantId", summary)
            self.assertEqual(row["sourceSystem"], "TBProfiler public results service")


if __name__ == "__main__":
    unittest.main()
