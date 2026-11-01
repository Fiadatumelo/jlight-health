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
    def __init__(self, patient_exists=True, include_events=False):
        self.patient_exists = patient_exists
        self.include_events = include_events
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
        if not self.include_events:
            if "FROM public.jl_bio_runs" in self.last_query:
                return [{
                    "id": "00000000-0000-4000-8000-000000000077",
                    "run_id": "SYNTH-RUN-001",
                    "analysis_type": "TBProfiler",
                    "pipeline": "TBProfiler",
                    "pipeline_version": "6.7.0",
                    "stage": "completed",
                    "submitted_at": None,
                    "completed_at": None,
                }]
            return []
        q = self.last_query.lower()
        if "from public.jl_admissions" in q:
            return [{"id":"adm-1","admitted_at":"2026-11-01T08:00:00Z","status":"admitted","admission_no":"ADM-SYN-1","source":"synthetic-his"}]
        if "from public.jl_clinical_orders" in q:
            return [{"id":"co-1","test_name":"Synthetic CRP","priority":"STAT","ordered_at":"2026-11-01T08:10:00Z","specimen_collected_at":"2026-11-01T08:15:00Z","result_received_at":"2026-11-01T08:45:00Z","clinical_action_at":None,"tat_hours":0.58,"tat_target_hours":1,"tat_breached":False,"journey_gap_flag":True}]
        if "from public.jl_lab_orders" in q:
            return [{"id":"lo-1","order_number":"ORD-SYN-1","priority":"STAT","ordered_at":"2026-11-01T08:10:00Z","received_at":"2026-11-01T08:20:00Z","resulted_at":"2026-11-01T08:40:00Z","status":"resulted"}]
        if "from public.jl_lab_samples" in q:
            return [{"id":"s-1","accession_no":"ACC-SYN-1","sample_type":"blood","collected_at":"2026-11-01T08:15:00Z","received_at":"2026-11-01T08:20:00Z","stage":"received"}]
        if "from public.jl_lab_results" in q:
            return [{"id":"lr-1","test_name":"Synthetic CRP","result_value":25,"result_text":None,"result_unit":"mg/L","interpretation":"high","is_critical":False,"critical_notified_at":None,"status":"verified","resulted_at":"2026-11-01T08:40:00Z","verified_at":"2026-11-01T08:42:00Z"}]
        if "from public.jl_bio_accessions" in q:
            return [{"id":"ba-1","accession_no":"BIO-SYN-1","sample_type":"isolate","collection_date":"2026-11-01","received_at":"2026-11-01T09:00:00Z"}]
        if "from public.jl_bio_runs" in q:
            return [{"id":"00000000-0000-4000-8000-000000000077","run_id":"SYNTH-RUN-001","analysis_type":"TBProfiler","pipeline":"TBProfiler","pipeline_version":"6.7.0","stage":"completed","submitted_at":"2026-11-01T09:05:00Z","completed_at":"2026-11-01T09:30:00Z"}]
        if "from public.jl_bio_qc" in q:
            return [{"id":"bq-1","run_id":"00000000-0000-4000-8000-000000000077","coverage_mean":64,"mapping_rate":84.69,"q_score":30,"dup_rate":5,"gc_content":65,"contamination":0.1,"qc_status":"pass"}]
        if "from public.jl_bio_amr" in q:
            return [{"id":"amr-1","run_id":"00000000-0000-4000-8000-000000000077","gene":"rpoB","antibiotic_class":"rifampicin","resistance_level":"resistance-associated","confidence":0.98,"database_version":"WHO-v2"}]
        if "from public.jlight_workflow_events" in q:
            return [{"event_id":"wf-1","domain":"laboratory","event_type":"critical_result_acknowledgement","observed_at":"2026-11-01T08:50:00Z","source_status":"acknowledged","source_record_id":"ACK-SYN-1"}]
        return []


class JourneyDB:
    def __init__(self, patient_exists=True, include_events=False):
        self.cursor_instance = JourneyCursor(patient_exists, include_events)
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


def test_patient_journey_integrates_all_three_care_domains_and_clinical_action_gap():
    db = JourneyDB(include_events=True)
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app._patient_journey_authorisation", return_value=(ORG_ID, {"hospital", "laboratory", "bioinformatics"}, None)), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().get(
            "/api/patient-journey/" + PATIENT_ID,
            headers={"Authorization": "Bearer verified-test-token"},
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["available_domains"] == ["bioinformatics", "hospital", "laboratory"]
    types = {event["event_type"] for event in body["events"]}
    assert {"admission", "clinical_order", "clinical_action_pending", "laboratory_order",
            "specimen_status", "laboratory_result", "bioinformatics_accession",
            "analysis_run", "quality_control", "resistance_finding",
            "critical_result_acknowledgement"}.issubset(types)
    pending = next(event for event in body["events"] if event["event_type"] == "clinical_action_pending")
    assert pending["status"] == "action_overdue_review"
    assert body["clinical_trials_included"] is False


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
