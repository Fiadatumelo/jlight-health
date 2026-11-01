"""Authenticated Patient Journey API tests: exact matching and domain-level isolation."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app

PATIENT_ID = "00000000-0000-4000-8000-000000000099"
ORG_ID = "00000000-0000-4000-8000-000000000088"
USER_ID = "00000000-0000-4000-8000-000000000001"


class JourneyCursor:
    def __init__(self, patient_exists=True):
        self.patient_exists = patient_exists
        self.last_query = ""
        self.params = ()
        self.executed = []

    def __enter__(self): return self
    def __exit__(self, *_args): return False

    def execute(self, query, params=None):
        self.last_query = query
        self.params = params or ()
        self.executed.append((query, self.params))

    def fetchone(self):
        if "FROM public.jl_patients" in self.last_query:
            return {"id": PATIENT_ID} if self.patient_exists else None
        return None

    def fetchall(self):
        return []


class JourneyDB:
    def __init__(self, patient_exists=True):
        self.cursor_instance = JourneyCursor(patient_exists)
        self.rollbacks = 0
    def cursor(self): return self.cursor_instance
    def rollback(self): self.rollbacks += 1


def claims():
    return {"sub": USER_ID, "aud": "authenticated"}


def test_patient_journey_requires_verified_bearer_token():
    response = app.test_client().get("/api/patient-journey/" + PATIENT_ID)
    assert response.status_code == 401


def test_patient_journey_returns_only_permitted_domains_and_excludes_trials():
    db = JourneyDB()
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app._patient_journey_authorisation", return_value=(ORG_ID, {"hospital", "laboratory"}, None)), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().get(
            "/api/patient-journey/" + PATIENT_ID,
            headers={"Authorization": "Bearer verified-test-token"},
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["available_domains"] == ["hospital", "laboratory"]
    assert body["clinical_trials_included"] is False
    assert body["events"] == []
    assert "bioinformatics" not in body["available_domains"]
    assert "clinical_trials" not in body["available_domains"]
    queries = [q.lower() for q, _ in db.cursor_instance.executed]
    assert any("jl_admissions" in q for q in queries)
    assert any("jl_clinical_orders" in q for q in queries)
    assert any("clinical_action_at" in q for q in queries)
    assert any("jl_lab_orders" in q for q in queries)
    assert not any("jl_bio_runs" in q for q in queries)
    assert not any("jl_trial_participant" in q for q in queries)


def test_patient_journey_rejects_patient_from_another_organisation():
    db = JourneyDB(patient_exists=False)
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app._patient_journey_authorisation", return_value=(ORG_ID, {"hospital"}, None)), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().get(
            "/api/patient-journey/" + PATIENT_ID,
            headers={"Authorization": "Bearer verified-test-token"},
        )
    assert response.status_code == 404
    assert "not found" in response.get_json()["error"].lower()


def test_patient_journey_includes_bioinformatics_accession_qc_and_amr():
    db = JourneyDB()
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app._patient_journey_authorisation", return_value=(ORG_ID, {"bioinformatics"}, None)), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().get(
            "/api/patient-journey/" + PATIENT_ID,
            headers={"Authorization": "Bearer verified-test-token"},
        )
    assert response.status_code == 200
    queries = [q.lower() for q, _ in db.cursor_instance.executed]
    assert any("jl_bio_accessions" in q for q in queries)
    assert any("jl_bio_runs" in q for q in queries)
    assert any("jl_bio_qc" in q for q in queries)
    assert any("jl_bio_amr" in q for q in queries)
    assert not any("jl_admissions" in q for q in queries)
    assert not any("jl_trial_participant" in q for q in queries)


def test_patient_journey_rejects_members_without_care_domain_read_access():
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app._patient_journey_authorisation", return_value=(None, None, (
             app.response_class(response='{"success":false}', status=403, mimetype="application/json"), 403
         ))):
        response = app.test_client().get(
            "/api/patient-journey/" + PATIENT_ID,
            headers={"Authorization": "Bearer verified-test-token"},
        )
    assert response.status_code == 403
