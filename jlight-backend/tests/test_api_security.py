"""API authentication regression tests. Run from jlight-backend with pytest."""
import sys
from pathlib import Path
from unittest.mock import patch
import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.app import app


def test_health_probe_is_public():
    response = app.test_client().get("/api/health")
    assert response.status_code == 200


def test_protected_route_rejects_missing_bearer_token():
    response = app.test_client().post("/api/bio/sequence", json={"sequence": "ATCGATCGATCG"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_protected_route_rejects_invalid_token():
    with patch("api.app.verify_access_token", side_effect=jwt.InvalidTokenError("bad token")):
        response = app.test_client().post(
            "/api/bio/sequence",
            headers={"Authorization": "Bearer invalid"},
            json={"sequence": "ATCGATCGATCG"},
        )
    assert response.status_code == 401


def test_protected_route_accepts_verified_session():
    claims = {"sub": "00000000-0000-4000-8000-000000000001", "aud": "authenticated"}
    with patch("api.app.verify_access_token", return_value=claims):
        response = app.test_client().post(
            "/api/bio/sequence",
            headers={"Authorization": "Bearer verified-test-token"},
            json={"sequence": "ATCGATCGATCG"},
        )
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_protected_route_rejects_empty_bearer_token():
    response = app.test_client().get("/api/audit", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
