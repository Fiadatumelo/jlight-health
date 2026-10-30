"""Security and contract tests for database-authorised JC routes."""
import sys
from pathlib import Path
from unittest.mock import patch
from flask import jsonify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app


def verified_claims(**overrides):
    claims = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "org_id": "attacker-controlled-token-org",
        "permissions": ["intelligence:read"],
        "role": "Laboratory",
    }
    claims.update(overrides)
    return claims


def scope(domain="laboratory", org_id="org-db-verified", user_id=None):
    return {
        "organisation_id": org_id,
        "organisation_type": domain,
        "user_id": user_id or verified_claims()["sub"],
    }, None


def denied_scope(*_args, **_kwargs):
    return None, (jsonify({"success": False, "error": "Path denied"}), 403)


def test_intelligence_route_requires_bearer_token():
    response = app.test_client().post("/api/intelligence/summary", json={})
    assert response.status_code == 401


def test_intelligence_uses_database_org_not_token_org():
    claims = verified_claims()
    trusted_scope = scope(user_id=claims["sub"])
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=trusted_scope), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 200
    assert response.get_json()["organisation_id"] == "org-db-verified"


def test_general_intelligence_rejects_trial_organisation():
    claims = verified_claims(role="Trial")
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", side_effect=denied_scope):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 403


def test_user_metadata_cannot_authorise_an_organisation():
    claims = {
        "sub": "00000000-0000-4000-8000-000000000003",
        "aud": "authenticated",
        "user_metadata": {
            "org_id": "attacker-controlled-org",
            "permissions": ["intelligence:read"],
            "jlight_role": "Laboratory",
        },
    }
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", side_effect=denied_scope):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 403


def test_intelligence_permission_is_required():
    claims = verified_claims(permissions=["system:read"])
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=scope(user_id=claims["sub"])), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 403


def test_raw_or_unknown_payload_fields_are_rejected():
    claims = verified_claims()
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=scope(user_id=claims["sub"])):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"patient_name": "Jane Doe"},
        )
    assert response.status_code == 400


def test_clinical_trials_route_uses_database_trial_scope():
    claims = verified_claims()
    trial_scope = scope("clinical_trials", "org-trial-db", claims["sub"])
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=trial_scope), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/clinical-trials-summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"clinical_trials_checks": [
                {"check_id": "overdue_visit", "status": "review", "severity": "medium", "evidence_count": 2},
                {"check_id": "adverse_event_followup", "status": "pass", "severity": "info", "evidence_count": 0},
            ]},
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["organisation_id"] == "org-trial-db"
    assert body["tool"] == "clinical_trials_summary"
    assert body["result"]["human_review_required"] is True


def test_clinical_trials_route_rejects_non_trial_database_scope():
    claims = verified_claims()
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", side_effect=denied_scope):
        response = app.test_client().post(
            "/api/intelligence/clinical-trials-summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"clinical_trials_checks": []},
        )
    assert response.status_code == 403


def test_clinical_trials_route_rejects_identifiers_and_unapproved_fields():
    claims = verified_claims()
    trial_scope = scope("clinical_trials", "org-trial-db", claims["sub"])
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app.resolve_verified_workspace_scope", return_value=trial_scope):
        response = app.test_client().post(
            "/api/intelligence/clinical-trials-summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"clinical_trials_checks": [
                {"check_id": "overdue_visit", "status": "review", "severity": "medium",
                 "evidence_count": 1, "participant_id": "direct-identifier"},
            ]},
        )
    assert response.status_code == 400
