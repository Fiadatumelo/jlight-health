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
            "other_variants": [],
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
        self.assertEqual(summary["resistanceVariants"][0]["annotations"][0]["drug"], "rifampicin")
        self.assertNotIn("patientId", summary)


if __name__ == "__main__":
    unittest.main()
