"""Release guards for canonical Bioinformatics patient linking.

These checks guard the source-level authorization and persistence contract.
Runtime database integration tests remain a separate release requirement.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
API = (ROOT / "jlight-backend" / "api" / "app.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def route_source(source, route):
    start = source.index(route)
    following = source.find("@app.route(", start + len(route))
    return source[start:following if following >= 0 else len(source)]


class CanonicalPatientBioinformaticsConnectionTests(unittest.TestCase):
    def test_patient_demographic_upsert_is_not_available_to_bioinformatics_only(self):
        route = route_source(API, '@app.route("/api/patients/upsert"')
        self.assertIn("@require_auth", route)
        self.assertIn('{"hospital", "laboratory"}, access="write"', route)
        self.assertNotIn('"bioinformatics"', route)
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", route)
        self.assertIn("ON CONFLICT (org_id,mrn)", route)

    def test_run_upsert_requires_bioinformatics_write_and_exact_tenant_patient(self):
        route = route_source(API, '@app.route("/api/bioinformatics/runs/upsert"')
        self.assertIn('@require_domain_auth({"bioinformatics"}, access="write")', route)
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", route)
        self.assertIn("coalesce(active,true)=true", route)
        self.assertIn("jl_bio_accessions", route)
        self.assertIn("jl_bio_runs", route)

    def test_run_and_accession_cannot_be_reassigned_or_diverge(self):
        route = route_source(API, '@app.route("/api/bioinformatics/runs/upsert"')
        self.assertIn("COALESCE(public.jl_bio_runs.accession_id,EXCLUDED.accession_id)", route)
        self.assertIn("public.jl_bio_runs.accession_id=EXCLUDED.accession_id", route)
        self.assertIn("Run and accession patient links conflict; no changes made", route)
        self.assertIn("accession_patient_id", route)
        self.assertIn("run_patient_id", route)

    def test_qc_and_amr_persist_without_mislabeling_median_as_mean(self):
        route = route_source(API, '@app.route("/api/bioinformatics/runs/upsert"')
        self.assertIn("INSERT INTO public.jl_bio_qc", route)
        self.assertIn("INSERT INTO public.jl_bio_amr", route)
        self.assertIn('numeric(qc.get("coverageMean"))', route)
        self.assertNotIn('numeric(qc.get("medianDepth"))', route)
        self.assertNotIn('finding.get("confidence") or "reported"', route)

    def test_patient_journey_reads_canonical_bioinformatics_tables_and_excludes_trials(self):
        journey = route_source(API, '@app.route("/api/patient-journey/<uuid:patient_id>"')
        for table in ("jl_patients", "jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"):
            self.assertIn(table, journey)
        self.assertIn("Clinical Trials is deliberately excluded", journey)
        self.assertIn('if "bioinformatics" in domains:', journey)

    def test_tbprofiler_initial_import_and_retry_preserve_mean_depth_and_amr_fields(self):
        initial = HTML[HTML.index("async function commitTBProfilerJson()"):
                       HTML.index("async function retryTBProfilerCloudSync()")]
        retry = HTML[HTML.index("async function retryTBProfilerCloudSync()"):
                     HTML.index("function hydrateTBProfilerRecord(")]
        self.assertIn("coverageMean:record.tbProfiler?.qc?.meanDepth", initial)
        self.assertIn("coverageMean:record.tbProfiler?.qc?.meanDepth", retry)
        for field in ("drug:x.drug", "mutation:x.mutation",
                      "annotationSource:x.source", "sourceConfidence:x.confidence"):
            self.assertIn(field, initial)
            self.assertIn(field, retry)

    def test_patient_uuid_is_never_demographically_matched(self):
        route = route_source(API, '@app.route("/api/bioinformatics/runs/upsert"')
        self.assertNotIn("full_name", route)
        self.assertNotIn("mrn", route)
        self.assertNotIn("date_of_birth", route)

    def test_bioinformatics_only_frontend_does_not_load_patient_demographics(self):
        loader_start = HTML.index("async function loadDomainDataFromBackend()")
        loader = HTML[loader_start:loader_start + 6000]
        self.assertIn("bioinformatics: ['bioRuns', 'bioAccessions', 'bioQc', 'bioAmr', 'reports']", loader)
        self.assertIn("p_domain: 'hospital'", loader)
        self.assertIn("p_domain: 'laboratory'", loader)
        self.assertIn("allowedDomainsByPath.bioinformatics.unshift('patients')", loader)
        self.assertIn("Canonical patient UUID", HTML)
        self.assertIn("data-tb-patient-id", HTML)



if __name__ == "__main__":
    unittest.main(verbosity=2)
