"""Regression tests for entitlement-based JLIGHT API workspace selection."""
import sys
from pathlib import Path
from unittest.mock import patch, Mock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app


class FakeCursor:
    def __init__(self, permissions=None):
        self.permissions = permissions or {"laboratory": True}
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        if "SELECT p.org_id::text AS organisation_id" in query:
            self.result = {"organisation_id": "org-db-verified"}
        elif "jlight_has_domain_permission" in query:
            _org_id, domain, _access = params
            self.result = {"allowed": self.permissions.get(domain, False)}
        else:
            self.result = None

    def fetchone(self):
        return self.result


class FakeDatabase:
    def __init__(self, permissions=None):
        self.permissions = permissions or {"laboratory": True}
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.permissions)

    def rollback(self):
        self.rollbacks += 1


def claims(**overrides):
    result = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "user_metadata": {"org_id": "attacker-controlled-org", "role": "Bioinformatics"},
    }
    result.update(overrides)
    return result


def post_csv(db, headers=None):
    auth_headers = {"Authorization": "Bearer verified-test-token"}
    auth_headers.update(headers or {})
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=db), \
         patch("api.app.analyse_csv", Mock(return_value={"success": True, "rowCount": 4})) as analysis, \
         patch("api.app.log_audit"):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers=auth_headers,
            json={"csvText": "sample,result\\nS1,positive", "role": "Hospital"},
        )
    return response, analysis


def test_single_entitled_workspace_is_selected_without_client_role_trust():
    db = FakeDatabase({"laboratory": True, "bioinformatics": False, "hospital": False})
    response, analysis = post_csv(db, {"X-Role": "Bioinformatics"})
    assert response.status_code == 200
    assert analysis.call_args.kwargs["role"] == "Laboratory"


def test_multi_workspace_requires_explicit_untrusted_selector_then_checks_entitlement():
    db = FakeDatabase({"laboratory": True, "bioinformatics": True, "hospital": False})
    response, _ = post_csv(db)
    assert response.status_code == 400
    assert "Select an authorised workspace" in response.get_json()["error"]

    response, analysis = post_csv(db, {"X-JLIGHT-Workspace": "bioinformatics", "X-Role": "Hospital"})
    assert response.status_code == 200
    assert analysis.call_args.kwargs["role"] == "Bioinformatics"


def test_forged_workspace_selector_cannot_grant_unentitled_path():
    db = FakeDatabase({"laboratory": True, "bioinformatics": False, "hospital": False})
    response, _ = post_csv(db, {"X-JLIGHT-Workspace": "bioinformatics", "X-Role": "Bioinformatics"})
    assert response.status_code == 403


def test_unsupported_workspace_selector_is_rejected_before_database_access():
    db = FakeDatabase({"laboratory": True})
    response, _ = post_csv(db, {"X-JLIGHT-Workspace": "clinical_trials"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", [
    "/api/bio/tb", "/api/bio/variant", "/api/bio/ngs",
    "/api/bio/wgs", "/api/bio/sequence", "/api/bio/fasta",
])
def test_raw_sequence_analysis_endpoints_are_not_part_of_jlight(path):
    response = app.test_client().post(path, json={"sequence": "ATCGATCGATCG"})
    assert response.status_code == 404



def test_workspace_api_fails_closed_when_database_is_unavailable():
    with patch("api.app.verify_access_token", return_value=claims()), \
         patch("api.app.get_db", return_value=None):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"csvText": "sample,result\\nS1,positive"},
        )
    assert response.status_code == 503
