# JLIGHT organisation invitation function

Function: `invite-organisation-member`

## Required Edge Function secrets
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` — server-side secret only; never expose it to browser code or commit it.
- `ALLOWED_ORIGINS` — semicolon-separated exact origins, for example `https://jlight-health.co.za;https://www.jlight-health.co.za` only if both are configured.
- `INVITE_REDIRECT_URL` — a verified HTTPS redirect URL on the JLIGHT site that completes Supabase invite acceptance.

## Behavior
- Requires a valid Supabase user access token.
- Checks the caller's active membership and role inside the target organisation using the trusted service client.
- Allows only owner/admin to invite; only owner may appoint an organisation administrator.
- Does not treat an organisation code as authentication.
- Uses a fixed allowlist of roles and validates organisation UUID and email shape.
- Uses restrictive CORS, no-store responses and generic invitation errors.

## Deployment and verification
Deploy only to a staging Supabase project first. Configure the secrets in Supabase Edge Function settings, not in GitHub or frontend JavaScript. Verify invite acceptance, duplicate email, duplicate membership, suspended/revoked caller, cross-organisation attempts, wrong-origin requests, expired tokens, mail delivery failures and rollback/recovery after an invite succeeds but membership insertion fails.

**Important:** This function is a scaffold and has not been deployed or integration-tested against the live JLIGHT Supabase project. Before production, add rate limiting/abuse controls, audit logging for invitation and membership changes, a robust idempotent invite lifecycle (including pending invitations), automated tests and administrator recovery tooling. Do not claim commercial readiness until those gates pass.

## Invitation activation
New invitations are stored with status `invited`, which grants no tenant access. After the recipient signs in and confirms their email, the authenticated client must call `jl_accept_organisation_invitations()`; it activates only membership rows attached to that authenticated user. Integrate this RPC into the verified invite-acceptance route and test expired links, unconfirmed emails, duplicate invitations and revoked memberships before production.
