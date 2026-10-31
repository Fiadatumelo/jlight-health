"""Unit tests for mapping TBProfiler JSON into JLIGHT's reviewable bioRuns contract."""
import json
import tempfile
import unittest
from pathlib import Path

from validation.tbprofiler.normalize_results import compact_variant, normalize_one


class TBProfilerNormalizerTests(unittest.TestCase):
    def test_preserves_tbprofiler_resistance_annotation_fields(self):
        result = compact_variant({
            "gene_name": "rpoB",
            "gene_id": "Rv0667",
            "pos": 761155,
            "protein_change": "p.Ser450Leu",
            "nucleotide_change": "c.1349C>T",
            "type": "missense_variant",
            "depth": 87,
            "freq": 0.96,
            "annotation": [{
                "drug": "rifampicin",
                "confidence": "high",
                "source": "WHO catalogue",
                "comment": "Resistance-associated mutation",
            }],
        })
        self.assertEqual(result["gene"], "rpoB")
        self.assertEqual(result["position"], 761155)
        self.assertEqual(result["proteinChange"], "p.Ser450Leu")
        self.assertEqual(result["nucleotideChange"], "c.1349C>T")
        self.assertEqual(result["depth"], 87)
        self.assertEqual(result["frequency"], 0.96)
        self.assertEqual(result["drugs"], ["rifampicin"])
        self.assertEqual(result["annotations"][0]["confidence"], "high")

    def test_low_coverage_tbprofiler_result_is_flagged_for_review(self):
        sample = {
            "id": "ERR_LOW_COVERAGE_TEST",
            "qc": {"median_depth": 12, "pct_reads_mapped": 99.3, "num_reads": 400000},
            "dr_variants": [],
            "other_variants": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_LOW_COVERAGE_TEST.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            row = normalize_one(path, "PRJEB_TEST", "6.7.0", "test-db-rev")
        summary = json.loads(row["summary"])
        self.assertEqual(row["qualityStatus"], "review_required_low_coverage")
        self.assertTrue(any("below the 30x review threshold" in note for note in summary["qcWarnings"]))
        self.assertEqual(summary["medianCoverage"], 12)
        self.assertEqual(summary["mappingRatePercent"], 99.3)

    def test_uses_verified_tool_version_and_extracts_database_commit(self):
        sample = {
            "id": "ERR_PROVENANCE_001",
            "pipeline": {"version": "", "db_version": {
                "name": "who_v2+", "commit": "fbd11a9065212bb576b729b80fd7a3feccaad8ff"
            }},
            "qc": {"pct_reads_mapped": 98.1},
            "dr_variants": [],
            "other_variants": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_PROVENANCE_001.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            row = normalize_one(path, "PRJEB_TEST", "6.7.0", "not_reported")
        summary = json.loads(row["summary"])
        self.assertEqual(summary["pipelineVersion"], "6.7.0")
        self.assertEqual(summary["databaseVersion"], "fbd11a9065212bb576b729b80fd7a3feccaad8ff")

    def test_normalized_summary_keeps_lineage_and_version_provenance(self):
        sample = {
            "id": "ERR_TEST_001",
            "timestamp": "2026-10-30T10:00:00Z",
            "main_lineage": "lineage4",
            "sub_lineage": "lineage4.3.4.1",
            "drtype": "MDR-TB",
            "pipeline": {"version": "6.7.0", "db_version": "test-db-rev"},
            "qc": {"median_depth": 48, "pct_reads_mapped": 97.5, "num_reads": 120000},
            "dr_variants": [{
                "gene_name": "rpoB",
                "protein_change": "p.Ser450Leu",
                "depth": 80,
                "freq": 0.95,
                "annotation": [{"drug": "rifampicin", "confidence": "high"}],
            }],
            "other_variants": [{
                "gene_name": "gyrA",
                "protein_change": "p.Ser95Thr",
                "type": "missense_variant",
                "depth": 74,
                "freq": 0.99,
                "annotation": [{"drug": "levofloxacin", "confidence": "not associated with resistance"}],
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_TEST_001.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            row = normalize_one(path, "PRJEB_TEST", "6.7.0", "test-db-rev")
        summary = json.loads(row["summary"])
        self.assertEqual(row["sourceRecordId"], "ERR_TEST_001")
        self.assertEqual(summary["mainLineage"], "lineage4")
        self.assertEqual(summary["subLineage"], "lineage4.3.4.1")
        self.assertEqual(summary["pipelineVersion"], "6.7.0")
        self.assertEqual(summary["databaseVersion"], "test-db-rev")
        self.assertEqual(summary["mappingRatePercent"], 97.5)
        self.assertEqual(summary["medianCoverage"], 48)
        self.assertEqual(summary["readCount"], 120000)
        self.assertEqual(summary["resistanceVariants"][0]["annotations"][0]["drug"], "rifampicin")
        self.assertEqual(summary["otherVariantCount"], 1)
        self.assertEqual(summary["otherVariants"][0]["gene"], "gyrA")
        self.assertEqual(summary["otherVariants"][0]["annotations"][0]["drug"], "levofloxacin")
        self.assertNotIn("patientId", summary)


if __name__ == "__main__":
    unittest.main()
