"""Supabase bearer-token verification shared by the JLIGHT API."""
from __future__ import annotations

import os
from functools import lru_cache

import jwt
from jwt import PyJWKClient

ALLOWED_ALGORITHMS = ["ES256", "RS256", "HS256"]


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    explicit = os.environ.get("SUPABASE_JWKS_URL", "").strip()
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    url = explicit or (f"{base}/auth/v1/.well-known/jwks.json" if base else "")
    if not url:
        raise RuntimeError("Supabase JWKS URL is not configured")
    return PyJWKClient(url, cache_keys=True, cache_jwk_set=True)


def verify_access_token(token: str) -> dict:
    """Validate a Supabase JWT signature, issuer, audience and required claims."""
    issuer = os.environ.get("SUPABASE_JWT_ISSUER", "").strip()
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    issuer = issuer or (f"{supabase_url}/auth/v1" if supabase_url else "")
    if not issuer:
        raise RuntimeError("SUPABASE_URL or SUPABASE_JWT_ISSUER is required")

    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ALGORITHMS:
        raise jwt.InvalidAlgorithmError("Unsupported JWT signing algorithm")

    if algorithm == "HS256":
        secret = os.environ.get("SUPABASE_JWT_SECRET", "")
        if not secret:
            raise RuntimeError("SUPABASE_JWT_SECRET is required for HS256 tokens")
        key = secret
        algorithms = ["HS256"]
    else:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        algorithms = ["ES256", "RS256"]

    claims = jwt.decode(
        token,
        key,
        algorithms=algorithms,
        audience="authenticated",
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise jwt.InvalidTokenError("Missing subject")
    return claims
