"""API authentication and retired-endpoint regression tests."""
import sys
import time
import jwt
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.app import app


def test_health_probe_is_public():
    response = app.test_client().get("/api/health")
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/analyse-csv", {"csvText": "cv\\n2.1\\n2.3\\n2.8"}),
        ("get", "/api/cards", None),
        ("post", "/api/cards/acknowledge", {"card_number": "test-card"}),
        ("get", "/api/audit", None),
    ],
)
def test_protected_routes_reject_missing_bearer_token(method, path, payload):
    response = getattr(app.test_client(), method)(path, json=payload)
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/bio/tb",
        "/api/bio/variant",
        "/api/bio/ngs",
        "/api/bio/wgs",
        "/api/bio/sequence",
        "/api/bio/fasta",
    ],
)
def test_raw_sequence_analysis_routes_are_retired(path):
    response = app.test_client().post(path, json={"sequence": "ATCG" * 100})
    assert response.status_code == 404


def test_protected_route_rejects_invalid_signed_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-only-secret")
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    response = app.test_client().post(
        "/api/analyse-csv",
        headers={"Authorization": "Bearer definitely-not-a-valid-jwt"},
        json={"csvText": "cv\\n2.1\\n2.3\\n2.8"},
    )
    assert response.status_code == 401


def test_protected_route_returns_503_when_verifier_unavailable():
    with patch("api.app.verify_access_token", side_effect=Exception("bad token")):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": "Bearer invalid"},
            json={"csvText": "cv\\n2.1\\n2.3\\n2.8"},
        )
    assert response.status_code == 503


def test_protected_route_accepts_verified_session(monkeypatch):
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
    with patch("api.app.analyse_csv", return_value={"success": True, "rowCount": 3}):
        response = app.test_client().post(
            "/api/analyse-csv",
            headers={"Authorization": f"Bearer {token}"},
            json={"csvText": "cv\\n2.1\\n2.3\\n2.8", "fileName": "test.csv"},
        )
    assert response.status_code == 200
    assert response.get_json()["success"] is True


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/cards", None),
        ("post", "/api/cards/acknowledge", {"card_number": "test-card"}),
        ("get", "/api/audit", None),
    ],
)
def test_unscoped_card_and_audit_endpoints_fail_closed_for_authenticated_user(method, path, payload):
    claims = {
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "authenticated",
    }
    with patch("api.app.verify_access_token", return_value=claims):
        response = getattr(app.test_client(), method)(
            path,
            headers={"Authorization": "Bearer verified-test-token"},
            json=payload,
        )
    assert response.status_code == 503
    assert "organisation-scoped permissions" in response.get_json()["error"]


def test_protected_route_rejects_empty_bearer_token():
    response = app.test_client().get("/api/audit", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
