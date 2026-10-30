"""API authentication regression tests. Run from jlight-backend with pytest."""
import sys
import time
import jwt
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.app import app


def test_health_probe_is_public():
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200



@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/analyse-csv", {"csvText": "value\\n1\\n2\\n3"}),
        ("post", "/api/bio/tb", {"sequence": "ATCGATCGATCG"}),
        ("post", "/api/bio/variant", {"reference": "ATCG", "sample": "ATCG"}),
        ("post", "/api/bio/ngs", {"sequence": "ATCGATCGATCG"}),
        ("post", "/api/bio/wgs", {"sequence": "ATCGATCGATCG"}),
        ("post", "/api/bio/sequence", {"sequence": "ATCGATCGATCG"}),
        ("post", "/api/bio/fasta", {"sequence": ">sample\\nATCGATCG"}),
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
        "/api/bio/sequence",
        headers={"Authorization": "Bearer definitely-not-a-valid-jwt"},
        json={"sequence": "ATCGATCGATCG"},
    )
    assert response.status_code == 401

def test_protected_route_returns_503_when_verifier_unavailable():
    client = app.test_client()
    with patch("api.app.verify_access_token", side_effect=Exception("bad token")):
        response = client.post(
            "/api/bio/sequence",
            headers={"Authorization": "Bearer invalid"},
            json={"sequence": "ATCGATCGATCG"},
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


def test_protected_route_rejects_empty_bearer_token():
    client = app.test_client()
    response = client.get("/api/audit", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
