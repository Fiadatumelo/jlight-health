"""Runtime route tests for canonical Bioinformatics patient linking.

Uses a deterministic fake DB cursor so authorization, exact-link and conflict
behaviour are exercised without touching staging or production records.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app

ORG_ID = "00000000-0000-4000-8000-000000000088"
USER_ID = "00000000-0000-4000-8000-000000000001"
PATIENT_ID = "00000000-0000-4000-8000-000000000099"
OTHER_PATIENT_ID = "00000000-0000-4000-8000-000000000098"
ACCESSION_ID = "00000000-0000-4000-8000-000000000077"
RUN_UUID = "00000000-0000-4000-8000-000000000076"
RUN_KEY = "SYNTH-RUN-001"


class BioinformaticsCursor:
    def __init__(self, patient_exists=True, run_conflict=False, link_mismatch=False):
        self.patient_exists = patient_exists
        self.run_conflict = run_conflict
        self.link_mismatch = link_mismatch
        self.last_query = ""
        self.params = ()
        self.result = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.last_query = query
        self.params = params or ()
        self.executed.append((query, self.params))
        q = " ".join(query.lower().split())
        self.result = None
        if "from public.jl_patients" in q:
            self.result = {"id": PATIENT_ID} if self.patient_exists else None
        elif "insert into public.jl_bio_accessions" in q:
            self.result = {"id": ACCESSION_ID, "patient_id": PATIENT_ID}
        elif "insert into public.jl_bio_runs" in q:
            self.result = None if self.run_conflict else {
                "id": RUN_UUID, "run_id": RUN_KEY,
                "patient_id": PATIENT_ID, "accession_id": ACCESSION_ID,
            }
        elif "select r.patient_id::text as run_patient_id" in q:
            self.result = {
                "run_patient_id": PATIENT_ID,
                "accession_patient_id": OTHER_PATIENT_ID if self.link_mismatch else PATIENT_ID,
            }
        elif "select id::text,run_id,patient_id::text,accession_id::text" in q:
            self.result = {
                "id": RUN_UUID, "run_id": RUN_KEY,
                "patient_id": PATIENT_ID, "accession_id": ACCESSION_ID,
            }

    def fetchone(self):
        return self.result

    def fetchall(self):
        return []


class BioinformaticsDB:
    def __init__(self, **kwargs):
        self.cursor_instance = BioinformaticsCursor(**kwargs)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def authenticated_request(db, *, resolver=None, payload=None):
    scope = ({"organisation_id": ORG_ID, "user_id": USER_ID}, None)
    if resolver is None:
        resolver = scope
    with patch("api.app.verify_access_token", return_value={"sub": USER_ID, "aud": "authenticated"}), \
         patch("api.app.resolve_verified_workspace_scope", return_value=resolver), \
         patch("api.app.get_db", return_value=db):
        return app.test_client().post(
            "/api/bioinformatics/runs/upsert",
            json=payload or {
                "run_id": RUN_KEY,
                "accession_no": "SYNTH-ACC-001",
                "analysis_type": "TBProfiler",
                "patient_id": PATIENT_ID,
                "pipeline": "TBProfiler",
                "pipeline_version": "6.7.0",
                "stage": "completed",
                "qc": {"status": "review", "coverageMean": 35.2, "mappingRate": 97.1},
                "amr": [{"gene": "rpoB", "antibioticClass": "rifamycins",
                         "resistanceLevel": "resistance-associated", "confidence": 0.98}],
            },
            headers={
                "Authorization": "Bearer synthetic-verified-token",
                "X-JLIGHT-Organisation": ORG_ID,
                "X-JLIGHT-Workspace": "bioinformatics",
            },
        )


def test_run_upsert_persists_exact_patient_link_and_qc_amr():
    db = BioinformaticsDB()
    response = authenticated_request(db)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["canonical_run_id"] == RUN_UUID
    assert body["canonical_accession_id"] == ACCESSION_ID
    assert body["run"]["patient_id"] == PATIENT_ID
    queries = [q.lower() for q, _ in db.cursor_instance.executed]
    assert any("insert into public.jl_bio_accessions" in q for q in queries)
    assert any("insert into public.jl_bio_runs" in q for q in queries)
    assert any("insert into public.jl_bio_qc" in q for q in queries)
    assert any("insert into public.jl_bio_amr" in q for q in queries)
    assert db.commits == 1
    assert db.rollbacks == 0


def test_run_upsert_rejects_patient_not_found_in_active_tenant():
    db = BioinformaticsDB(patient_exists=False)
    response = authenticated_request(db)
    assert response.status_code == 404
    assert db.commits == 0
    assert db.rollbacks == 1
    assert not any("insert into public.jl_bio_accessions" in q.lower()
                   for q, _ in db.cursor_instance.executed)


def test_run_upsert_rejects_existing_run_link_conflict():
    db = BioinformaticsDB(run_conflict=True)
    response = authenticated_request(db)
    assert response.status_code == 409
    assert db.commits == 0
    assert db.rollbacks == 1


def test_run_upsert_rejects_run_accession_patient_mismatch():
    db = BioinformaticsDB(link_mismatch=True)
    response = authenticated_request(db)
    assert response.status_code == 409
    assert "conflict" in response.get_json()["error"].lower()
    assert db.commits == 0
    assert db.rollbacks == 1


def test_run_upsert_rejects_missing_bioinformatics_write_permission():
    db = BioinformaticsDB()
    denied = (None, (app.response_class(
        response='{"success":false,"error":"Workspace permission denied"}',
        status=403, mimetype="application/json"
    ), 403))
    response = authenticated_request(db, resolver=denied)
    assert response.status_code == 403
    assert db.commits == 0
    assert not db.cursor_instance.executed
