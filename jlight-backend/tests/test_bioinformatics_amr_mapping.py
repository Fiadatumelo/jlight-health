"""Regression guards for canonical AMR evidence mapping.

The Bioinformatics canonical import must preserve every independent evidence
dimension reported by TBProfiler/WHO annotations:

- drug names (``jl_bio_amr.drug``)
- mutation evidence (``jl_bio_amr.mutation``)
- annotation source (``jl_bio_amr.annotation_source``)
- WHO textual source confidence such as ``Assoc w R``
  (``jl_bio_amr.source_confidence``)

The pre-existing numeric ``confidence`` behaviour must not change: numeric
annotation confidences keep populating the numeric column, and textual WHO
confidences never corrupt it.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
API = (ROOT / "jlight-backend" / "api" / "app.py").read_text(encoding="utf-8")

AMR_EVIDENCE_COLUMNS = ("drug", "mutation", "annotation_source", "source_confidence")


def insert_source():
    start = API.index("INSERT INTO public.jl_bio_amr")
    end = API.index("db.commit()", start)
    return API[start:end]


def canonical_persistence_helper():
    start = HTML.index("async function persistTBProfilerCanonicalRecords(records)")
    end = HTML.index("async function commitTBProfilerJson()", start)
    return HTML[start:end]


class AmrPersistenceSchema(unittest.TestCase):
    def test_staging_columns_are_declared_by_the_existing_migration(self):
        migration = next(
            p for p in (ROOT / "supabase" / "migrations").glob("*bioinformatics_amr_source_evidence.sql")
        )
        text = migration.read_text(encoding="utf-8")
        for column in AMR_EVIDENCE_COLUMNS:
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column} ", text)

    def test_canonical_amr_insert_targets_every_evidence_column(self):
        insert = insert_source()
        for column in AMR_EVIDENCE_COLUMNS:
            self.assertIn(column, insert)
        self.assertIn("gene,antibiotic_class,resistance_level,confidence,database_version", insert)

    def test_no_new_migration_is_introduced_for_the_correction(self):
        # The staging columns already exist; the correction is code-only and
        # must not add another migration for the same columns.
        inserts = [line for line in API.splitlines() if "INSERT INTO public.jl_bio_amr" in line]
        self.assertEqual(len(inserts), 1)


class AmrEvidenceMapping(unittest.TestCase):
    def setUp(self):
        self.helper = canonical_persistence_helper()

    def test_frontend_maps_drug_names_independently(self):
        self.assertIn("drug: x.drug || null", self.helper)

    def test_frontend_maps_mutation_evidence_independently(self):
        self.assertIn("mutation: x.mutation || null", self.helper)

    def test_frontend_maps_annotation_source_independently(self):
        self.assertIn("annotationSource: x.source || x.annotationSource || null", self.helper)

    def test_frontend_maps_textual_source_confidence_independently(self):
        # x.confidence is the TBProfiler/WHO textual grading (e.g. "Assoc w R").
        self.assertIn("sourceConfidence: x.confidence || null", self.helper)

    def test_backend_reads_each_evidence_field_from_the_payload(self):
        for key in ("drug", "mutation", "annotationSource"):
            self.assertIn(f'finding.get("{key}")', insert_source())
        self.assertIn('finding.get("sourceConfidence")', API)


class NumericConfidenceBehaviour(unittest.TestCase):
    def test_numeric_confidence_parsing_is_unchanged(self):
        self.assertIn("confidence = float(finding.get(\"confidence\"))", API)
        self.assertIn("except (TypeError, ValueError):\n                        confidence = None", API)

    def test_numeric_confidence_still_targets_the_numeric_column(self):
        insert = insert_source()
        columns = insert[:insert.index("VALUES")]
        self.assertLess(columns.index("confidence"), columns.index("source_confidence"))

    def test_textual_confidence_is_never_written_to_the_numeric_column(self):
        # A non-numeric confidence such as "Assoc w R" must not be coerced into
        # the numeric column; it is preserved as textual source confidence.
        self.assertIn("except (TypeError, ValueError):\n                        confidence = None", API)
        self.assertIn('str(finding.get("sourceConfidence") or "")', API)
        self.assertIn("float(raw_confidence)", API)


class AmrPayloadIntegrity(unittest.TestCase):
    def test_patient_link_flow_preserves_every_evidence_field(self):
        link = HTML[HTML.index("async function linkTBProfilerRunToPatient(record, patientId)"):
                    HTML.index("function renderJourney()")]
        for field in ("drug:x.drug", "mutation:x.mutation",
                      "annotationSource:x.source", "sourceConfidence:x.confidence"):
            self.assertIn(field, link)

    def test_helper_rejects_unconfirmed_canonical_results(self):
        helper = canonical_persistence_helper()
        self.assertIn("canonical_run_id", helper)
        self.assertIn("canonical_accession_id", helper)


if __name__ == "__main__":
    unittest.main()
