# JLIGHT Flask backend — security release gate

Reviewed: `jlight-backend/api/app.py` in the masterplatform development branch.

## Current findings — block production exposure until fixed

1. **Authentication middleware added in this branch.** All API routes except `/api/health` require a verified Supabase bearer token. This is code-reviewed but not yet deployed or runtime-tested.
2. **Client-supplied role is trusted.** Several handlers read `X-Role` or a JSON `role` field. These values are user-controlled and must never determine permissions.
3. **Audit and decision-card routes now fail closed.** `/api/audit`, `/api/cards`, and `/api/cards/acknowledge` return 503 even for authenticated users until tenant-scoped authorization is implemented. This is a temporary safety gate, not a completed feature.
4. **Decision-card acknowledgement is not authorised or tenant-scoped.** `POST /api/cards/acknowledge` updates a card by card number without verifying organisation membership or permission.
5. **Decision cards have no tenant boundary in their query.** `GET /api/cards` filters by a caller-supplied role label, not a verified membership.
6. **Errors can disclose implementation details.** Some bioinformatics handlers return raw exception messages to callers.
7. **The app accepts large uploads.** A 50 MB request limit alone is not sufficient abuse protection for CPU-intensive sequence and spreadsheet processing.
8. **Optional database mode silently degrades.** Audit persistence failures are swallowed; health output reports a generic status that can be mistaken for full operational readiness.
9. **No demonstrated integration between Supabase membership RLS and Flask persistence.** The Flask API uses a separate PostgreSQL connection and must independently enforce user/tenant access or call trusted database functions safely.

## Required remediation order

1. Runtime-test Supabase access-token verification (issuer, audience, signature and expiry); keep only `/api/health` public.
2. Derive user identity from verified token claims. Ignore client-provided role fields for authorisation.
3. Add organisation membership checks for every read/write route; require organisation IDs and scope every query by authorised membership.
4. Make audit records user/organisation scoped and append-only; protect acknowledgement with role checks and audit events.
5. Apply per-route request-size, sequence-length, row-count and timeout limits; add rate limiting and safe generic errors.
6. Add tests for unauthenticated requests, invalid/expired tokens, cross-tenant access, read-only users, role escalation, oversized payloads and database outages.
7. Connect the frontend session to the API using a bearer token and verified organisation context; then run end-to-end tests.
8. Deploy to staging only after tests pass. Do not expose the Flask API publicly as a commercial service before these controls are verified.

## Important

This document is a review finding, not evidence that these controls have already been implemented. The existing Python engine tests exercise analytical functions but do not establish API authentication or tenant isolation. Do not send identifiable patient data to this API until remediation and independent security validation are complete.

## Branch implementation status

The development branch adds `api/security.py`, a `before_request` verifier and API authentication regression tests. It deliberately returns HTTP 503 for legacy audit and decision-card routes until organisation membership and tenant-scoped database access are implemented. The browser has not yet been wired to send the Supabase session token to the Flask service. Do not merge/deploy this change until frontend integration and staging tests pass.
