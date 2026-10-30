"""Regression tests for database-enforced JLIGHT organisation paths."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app


class FakeCursor:
    def __init__(self, org_type="laboratory", allowed=True):
        self.org_type = org_type
        self.allowed = allowed
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        if "SELECT p.org_id::text AS organisation_id" in query:
            self.result = {
                "organisation_id": "org-db-verified",
                "organisation_type": self.org_type,
            }
        elif "jlight_has_domain_permission" in query:
            self.result = {"allowed": self.allowed}
        else:
            self.result = None

    def fetchone(self):
        return self.result


class FakeDatabase:
    def __init__(self, org_type="laboratory", allowed=True):
        self.org_type = org_type
        self.allowed = allowed
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.org_type, self.allowed)

    def rollback(self):
        self.rollbacks += 1


def claims(**overrides):
    result = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
    }
    result.update(overrides)
    return result


def test_csv_analysis_uses_database_path_not_x_role_or_json_role():
    db = FakeDatabase(org_type="laboratory", allowed=True)
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=db), \
         patch("api.app.analyse_csv", return_value={"success": True, "rowCount": 4}), \
         patch("api.app.log_audit"):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={
                "Authorization": "Bearer verified-test-token",
                "X-Role": "Bioinformatics",
            },
            json={"csvText": "sample,result\nS1,positive", "role": "Bioinformatics"},
        )
    assert response.status_code == 200


def test_bioinformatics_api_rejects_laboratory_organisation():
    db = FakeDatabase(org_type="laboratory", allowed=True)
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().post(
            "/api/bio/sequence",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"sequence": "ATCGATCGATCG"},
        )
    assert response.status_code == 403


def test_database_permission_denial_blocks_workspace_api():
    db = FakeDatabase(org_type="laboratory", allowed=False)
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=db):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"csvText": "sample,result\nS1,positive"},
        )
    assert response.status_code == 403


def test_workspace_api_fails_closed_when_database_is_unavailable():
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=None):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"csvText": "sample,result\nS1,positive"},
        )
    assert response.status_code == 503


def test_database_scope_ignores_user_metadata_organisation_claims():
    db = FakeDatabase(org_type="laboratory", allowed=True)
    user_claims = claims(user_metadata={
        "org_id": "attacker-controlled-org",
        "role": "Bioinformatics",
    })
    with patch("api.app.verify_access_token", return_value=user_claims), \
         patch("api.app.get_db", return_value=db), \
         patch("api.app.analyse_csv", return_value={"success": True, "rowCount": 1}), \
         patch("api.app.log_audit"):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"csvText": "sample,result\nS1,positive"},
        )
    assert response.status_code == 200
