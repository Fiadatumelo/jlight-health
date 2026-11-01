"""Regression coverage for TBProfiler 6.7.0's actual JSON QC schema."""
import json
import tempfile
import unittest
from pathlib import Path
from validation.tbprofiler.normalize_results import normalize_one

class TBProfiler67SchemaTests(unittest.TestCase):
    def test_actual_tbprofiler_qc_fields_and_target_qc_are_preserved(self):
        sample = {
            "id": "ERR_SCHEMA_001",
            "timestamp": "2026-10-31T10:00:00Z",
            "pipeline": {"software_version": "6.7.0", "db_version": {"name": "who_v2+", "commit": "fbd11a90"}},
            "main_lineage": "lineage4", "sub_lineage": "lineage4.7",
            "lineage": [{"fraction": 100.0, "lineage": "lineage4.7"}],
            "drtype": "RR-TB",
            "qc": {"percent_reads_mapped": 78.45, "num_reads_mapped": 776926,
                   "target_median_depth": 22.0, "genome_median_depth": 21.0,
                   "target_qc": [{"target": "rpoB", "median_depth": 21.0, "percent_depth_pass": 97.74}]},
            "dr_variants": [{"gene_name": "rpoB", "protein_change": "p.Ser450Leu"}],
            "other_variants": []
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_SCHEMA_001.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            row = normalize_one(path, "PRJEB57919", "6.7.0", "fbd11a9065212bb576b729b80fd7a3feccaad8ff")
        summary = json.loads(row["summary"])
        self.assertEqual(row["qualityStatus"], "review_required_low_coverage")
        self.assertEqual(summary["genomeMedianCoverage"], 21.0)
        self.assertEqual(summary["targetMedianCoverage"], 22.0)
        self.assertEqual(summary["medianCoverage"], 22.0)
        self.assertEqual(summary["mappingRatePercent"], 78.45)
        self.assertEqual(summary["mappedReadCount"], 776926)
        self.assertEqual(summary["mainLineage"], "lineage4")
        self.assertEqual(summary["subLineage"], "lineage4.7")
        self.assertEqual(summary["targetQc"][0]["target"], "rpoB")
        self.assertEqual(summary["resistanceVariantCount"], 1)


    def test_pinned_full_database_commit_overrides_abbreviated_metadata(self):
        sample = {
            "id": "ERR_DB_PIN_001",
            "pipeline": {"software_version": "6.7.0", "db_version": {"name": "who_v2+", "commit": "fbd11a90"}},
            "qc": {"target_median_depth": 64.0, "genome_median_depth": 64.0},
            "dr_variants": [], "other_variants": []
        }
        full_commit = "fbd11a9065212bb576b729b80fd7a3feccaad8ff"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_DB_PIN_001.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            row = normalize_one(path, "PRJEB57919", "6.7.0", full_commit)
        summary = json.loads(row["summary"])
        self.assertEqual(summary["databaseVersion"], full_commit)
        self.assertEqual(summary["medianCoverage"], 64.0)

    def test_rejects_database_metadata_that_conflicts_with_pinned_commit(self):
        sample = {
            "id": "ERR_DB_MISMATCH_001",
            "pipeline": {"software_version": "6.7.0", "db_version": {"commit": "deadbeef"}},
            "qc": {"target_median_depth": 64.0}, "dr_variants": [], "other_variants": []
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ERR_DB_MISMATCH_001.results.json"
            path.write_text(json.dumps(sample), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                normalize_one(path, "PRJEB57919", "6.7.0", "fbd11a9065212bb576b729b80fd7a3feccaad8ff")

if __name__ == "__main__":
    unittest.main()
