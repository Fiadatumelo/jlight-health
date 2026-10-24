# JLIGHT authentication email setup

The frontend uses the `send-password-reset` Edge Function for password recovery and `send-organisation-code` for workspace-code delivery. Both send mail through Resend so these flows do not depend on Supabase's restricted default SMTP service.

## Required Supabase Edge Function secrets

Set these in the staging project's Edge Function secrets (never in frontend JavaScript or Git):
- `RESEND_API_KEY` — Resend API key.
- `JLIGHT_FROM_EMAIL` — sender address on a domain verified in Resend, e.g. `JLIGHT <auth@your-verified-domain>`.
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` — Supabase server-provided values; the service-role key must remain secret.
- Optional `JLIGHT_SITE_URL` — defaults to `https://jlight-health.co.za`.
- `INVITE_REDIRECT_URL` — the approved invite completion URL on the JLIGHT site.
- Optional `ALLOWED_ORIGINS` — semicolon-separated exact origins; defaults to the canonical JLIGHT domain, `www`, and the current PR preview. Update this for each new preview if needed.

## Supabase Auth URL configuration

In Authentication → URL Configuration, set the Site URL to `https://jlight-health.co.za/` and add that exact origin and recovery path to the Redirect URLs allowlist. Keep localhost only in development and remove it from production configuration if not needed.

## Password reset flow

1. The frontend invokes `send-password-reset` with the requested email.
2. The function generates a one-time Supabase recovery link through the admin Auth API and emails it via Resend.
3. The frontend exchanges a PKCE code, verifies a recovery token hash, or accepts Supabase recovery tokens from the URL.
4. The password form requires a valid recovery session and matching password entries before updating the password.
5. The user is signed out after the password changes.

The endpoint uses a generic success message to avoid disclosing whether an email address is registered. Its in-memory IP throttle is best-effort only; configure CAPTCHA and durable abuse protection before a public launch.

## Organisation code delivery

The owner can view/copy the code in Settings. Member invitations use `invite-organisation-member` and require `INVITE_REDIRECT_URL`, the Supabase server keys, and a verified Resend sender. The generic invitation endpoint deliberately excludes Clinical Trials; those memberships require the separately approved provisioning workflow. The email function requires a valid signed-in session and verifies that the caller owns the requested organisation before sending the code to the account email address. An organisation code is an identifier, not an authentication credential; membership still requires authorised onboarding.

## Staging smoke tests

- Request reset for a known test account and unknown address; the public responses should not reveal account existence.
- Confirm mail delivery and that the link opens `https://jlight-health.co.za/` (never localhost in production).
- Test expired/reused link, wrong password confirmation, successful reset, sign-in using the new password, and sign-in failure with the old password.
- Create a staging organisation, verify the code is shown, trigger Email code in Settings, and confirm the email arrives only at the verified owner email.
- Test wrong origin, unauthenticated organisation-code send, non-owner send, Resend rejection, and rate limits.
- Do not deploy to production until provider secrets are configured and all tests pass.
