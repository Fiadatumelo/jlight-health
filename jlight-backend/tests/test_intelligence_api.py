"""Security and contract tests for the authenticated AI/JC integration route."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app


def verified_claims(**overrides):
    claims = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
        "org_id": "org-test-1",
        "permissions": ["intelligence:read"],
        "role": "Laboratory",
    }
    claims.update(overrides)
    return claims


def test_intelligence_route_requires_bearer_token():
    response = app.test_client().post("/api/intelligence/summary", json={})
    assert response.status_code == 401


def test_intelligence_route_returns_privacy_minimised_summary():
    with patch("api.app.verify_access_token", return_value=verified_claims()), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={
                "csv_analysis": {
                    "severity": "critical", "riskScore": 84,
                    "filename": "patient-name-secret.csv",
                    "summary": "private free text must not leak",
                }
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["organisation_id"] == "org-test-1"
    assert body["agent"] == "JC"
    assert body["tool"] == "intelligence_summary"
    assert body["result"]["human_review_required"] is True
    assert "patient-name-secret.csv" not in str(body)
    assert "private free text must not leak" not in str(body)


def test_clinical_trials_scope_is_rejected_before_execution():
    claims = verified_claims(role="Trial", clinical_trials_scope=True)
    with patch("api.app.verify_access_token", return_value=claims):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 403


def test_intelligence_permission_is_required():
    claims = verified_claims(permissions=["system:read"])
    with patch("api.app.verify_access_token", return_value=claims), \
         patch("api.app._write_jc_audit"):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"journey_checks": []},
        )
    assert response.status_code == 403


def test_raw_or_unknown_payload_fields_are_rejected():
    with patch("api.app.verify_access_token", return_value=verified_claims()):
        response = app.test_client().post(
            "/api/intelligence/summary",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"patient_name": "Jane Doe"},
        )
    assert response.status_code == 400
