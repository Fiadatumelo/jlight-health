"""Static release guards for the canonical patient/Bioinformatics connection."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
API = (ROOT / "jlight-backend/api/app.py").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class CanonicalPatientBioinformaticsConnectionTests(unittest.TestCase):
    def test_patient_upsert_is_authenticated_tenant_scoped_and_returns_uuid(self):
        start = API.index('@app.route("/api/patients/upsert"')
        end = API.index('@app.route("/api/bioinformatics/runs/upsert"', start)
        route = API[start:end]
        self.assertIn("@require_auth", route)
        self.assertIn('access="write"', route)
        self.assertIn("resolve_verified_workspace_scope", route)
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", route)
        self.assertIn("ON CONFLICT (org_id,mrn)", route)
        self.assertIn('"canonical_patient_id": row["id"]', route)

    def test_bioinformatics_run_link_requires_bioinformatics_write_and_exact_patient(self):
        start = API.index('@app.route("/api/bioinformatics/runs/upsert"')
        end = API.index("# ─── Authoritative Patient Journey", start)
        route = API[start:end]
        self.assertIn('@require_domain_auth({"bioinformatics"}, access="write")', route)
        self.assertIn("WHERE id=%s::uuid AND org_id=%s::uuid", route)
        self.assertIn("jl_bio_accessions", route)
        self.assertIn("jl_bio_runs", route)
        self.assertIn("patient_id=COALESCE(EXCLUDED.patient_id", route)
        self.assertIn("already linked to a different patient", route)

    def test_tbprofiler_qc_and_amr_are_persisted_for_journey(self):
        start = API.index('@app.route("/api/bioinformatics/runs/upsert"')
        end = API.index("# ─── Authoritative Patient Journey", start)
        route = API[start:end]
        self.assertIn("INSERT INTO public.jl_bio_qc", route)
        self.assertIn("INSERT INTO public.jl_bio_amr", route)
        self.assertIn("DELETE FROM public.jl_bio_qc", route)
        self.assertIn("DELETE FROM public.jl_bio_amr", route)

    def test_frontend_uses_canonical_patient_and_run_apis(self):
        self.assertIn("jlightCanonicalApiRequest('/api/patients/upsert'", HTML)
        self.assertIn("canonicalPatientId", HTML)
        self.assertIn("jlightCanonicalApiRequest('/api/bioinformatics/runs/upsert'", HTML)
        self.assertIn("renderTBProfilerPatientLinkPanel(all)", HTML)
        self.assertIn("linkTBProfilerRunToPatient", HTML)

    def test_patient_journey_reads_canonical_bioinformatics_tables(self):
        journey = API[API.index('@app.route("/api/patient-journey/<uuid:patient_id>"'):]
        for table in ("jl_patients", "jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"):
            self.assertIn(table, journey)
        self.assertIn("r.patient_id=%s::uuid", journey)


if __name__ == "__main__":
    unittest.main()
