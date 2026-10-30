"""API authentication regression tests. Run from jlight-backend with pytest."""
import sys
import time
import jwt
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.app import app, resolve_verified_workspace_scope
from flask import g


def test_health_probe_is_public():
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200



@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/analyse-csv", {"csvText": "value\\n1\\n2\\n3"}),
        ("get", "/api/cards", None),
        ("post", "/api/cards/acknowledge", {"id": "test-card"}),
        ("get", "/api/audit", None),
    ],
)
def test_all_data_routes_reject_missing_bearer_token(method, path, payload):
    client = app.test_client()
    response = getattr(client, method)(path, json=payload)
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_protected_route_rejects_invalid_signed_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-only-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    client = app.test_client()
    response = client.post(
        "/api/analyse-csv",
        headers={"Authorization": "Bearer definitely-not-a-valid-jwt"},
        json={"csvText": "sample,result\\nS1,positive"},
    )
    assert response.status_code == 401

def test_protected_route_returns_503_when_verifier_unavailable():
    client = app.test_client()
    with patch("api.app.verify_access_token", side_effect=Exception("bad token")):
        response = client.post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer invalid"},
            json={"csvText": "sample,result\\nS1,positive"},
        )
    assert response.status_code == 503


def test_protected_route_fails_closed_without_database_path_authorization(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-only-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    now = int(time.time())
    claims = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "iss": "https://test-project.supabase.co/auth/v1",
        "iat": now,
        "exp": now + 60,
    }
    token = jwt.encode(claims, "test-only-secret", algorithm="HS256")
    with patch("api.app.get_db", return_value=None):
        response = app.test_client().post(
            "/api/bio/sequence",
            headers={"Authorization": f"Bearer {token}"},
            json={"sequence": "ATCGATCGATCG"},
        )
    assert response.status_code == 503
    assert response.get_json()["error"] == "Organisation authorization service unavailable"




def test_workspace_scope_honours_selected_organisation_only_after_membership_check():
    organisation_id = "00000000-0000-4000-8000-000000000099"

    class FakeCursor:
        def __init__(self):
            self.statements = []
            self.rows = [
                {"organisation_id": organisation_id},
                {"allowed": True},
            ]
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def execute(self, statement, params=None):
            self.statements.append((statement, params))
        def fetchone(self):
            return self.rows.pop(0)

    class FakeDB:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.rollbacks = 0
        def cursor(self):
            return self.cursor_instance
        def rollback(self):
            self.rollbacks += 1

    fake_db = FakeDB()
    with app.test_request_context(
        "/api/intelligence/clinical-trials-summary",
        headers={
            "X-JLIGHT-Organisation": organisation_id,
            "X-JLIGHT-Workspace": "clinical_trials",
        },
    ):
        g.auth_claims = {"sub": "00000000-0000-4000-8000-000000000001"}
        with patch("api.app.get_db", return_value=fake_db):
            scope, error = resolve_verified_workspace_scope({"clinical_trials"}, access="read")
    assert error is None
    assert scope["organisation_id"] == organisation_id
    assert scope["workspace"] == "clinical_trials"
    membership_query = fake_db.cursor_instance.statements[1][0]
    assert "jlight_organization_memberships" in membership_query
    assert "jl_org_memberships" in membership_query



def test_clinical_trials_intelligence_rejects_client_supplied_evidence():
    claims = {"sub": "00000000-0000-4000-8000-000000000001", "aud": "authenticated"}
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=({"organisation_id": "00000000-0000-4000-8000-000000000099"}, None)), \
         patch("api.app.get_db") as get_db:
        response = app.test_client().post(
            "/api/intelligence/clinical-trials-summary",
            headers={"Authorization": "Bearer test", "X-JLIGHT-Workspace": "clinical_trials"},
            json={"clinical_trials_checks": [
                {"check_id": "adverse_event_followup", "status": "pass", "severity": "info", "evidence_count": 0}
            ]},
        )
    assert response.status_code == 400
    assert "not accepted" in response.get_json()["error"]
    get_db.assert_not_called()


def test_clinical_trials_intelligence_uses_server_derived_database_checks():
    claims = {"sub": "00000000-0000-4000-8000-000000000001", "aud": "authenticated"}
    checks = [
        {"check_id": "adverse_event_followup", "status": "review", "severity": "high", "evidence_count": 2}
    ]

    class FakeCursor:
        def __init__(self):
            self.statements = []
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def execute(self, statement, params=None):
            self.statements.append((statement, params))
        def fetchone(self):
            return {"checks": checks}

    class FakeDB:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.rollbacks = 0
        def cursor(self):
            return self.cursor_instance
        def rollback(self):
            self.rollbacks += 1

    fake_db = FakeDB()
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=({"organisation_id": "00000000-0000-4000-8000-000000000099"}, None)), \
         patch("api.app.get_db", return_value=fake_db), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/clinical-trials-summary",
            headers={"Authorization": "Bearer test", "X-JLIGHT-Workspace": "clinical_trials"},
            json={},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "succeeded"
    assert body["result"]["overall_status"] == "review_required"
    assert body["result"]["human_review_required"] is True
    assert body["result"]["finding_count"] == 1
    assert any("jl_build_trial_intelligence_checks" in statement for statement, _ in fake_db.cursor_instance.statements)
    assert fake_db.rollbacks >= 1


def test_protected_route_rejects_empty_bearer_token():
    client = app.test_client()
    response = client.get("/api/audit", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
