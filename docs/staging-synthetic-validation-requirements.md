# JLIGHT staging synthetic-data requirements

Status: specification only; no accounts or database rows are created by this document.

## Safety boundary

- Use only the dedicated Supabase staging project `ampkysrzliwjtvbigsvu`.
- Do not point staging tests at production project `wrdwzpmpsbtkrwonejhp`.
- Never use real patient identifiers, real patient records, production access tokens, or production database credentials.
- Create synthetic identities in Supabase Auth and synthetic organization memberships only in staging.
- Do not grant `service_role` to the API or to test users. The API must use its restricted database role and RLS.
- Never disable RLS or loosen existing policies to make a test pass.
- Keep Clinical Trials isolated from the Hospital/Laboratory/Bioinformatics patient journey.
- All probes in the live authorization workflow must be read-only. Test data setup and cleanup must be separate, explicitly staging-scoped operations.
- Do not merge/deploy to production based on these tests alone.

## Minimal synthetic fixture

Create two synthetic users and two separate staging organizations.

| Fixture | Required setup |
|---|---|
| Synthetic User A | Supabase Auth user; active membership in Org A only; non-viewer role |
| Synthetic User B | Supabase Auth user; active membership in Org B only; non-viewer role |
| Org A | Synthetic organization UUID; no production identifiers |
| Org B | Different synthetic organization UUID |
| User A permissions | Explicit `can_read=true` and `can_report=true` for Hospital, Laboratory, Bioinformatics in Org A. Only grant `can_write=true` if a separate write test explicitly requires it. |
| User B permissions | Minimal explicit permission needed to prove valid membership in Org B. No permissions in Org A. |
| Patient fixture | Synthetic-only patient key and source records in Org A, linked only through an explicit verified synthetic link event. Never infer a verified link from a matching name/date of birth. |
| Isolation fixture | No membership or domain permission for User A in Org B or User B in Org A. |
| Clinical Trials fixture | Separate synthetic trial-only record, never included in the cross-domain operational patient journey. |

Use obviously synthetic labels such as `SYNTH-JLIGHT-001`; do not use real names, real national ID numbers, real MRNs, or plausible live contact details. Random UUIDs should be generated at setup time and kept in staging-only environment/secrets.

## Acceptance tests

1. Missing bearer token is rejected with HTTP 401.
2. Invalid/expired bearer token is rejected with HTTP 401.
3. Valid User A token with Org B selected is rejected with HTTP 403.
4. Valid User B token with Org A selected is rejected with HTTP 403.
5. User A can read only the explicitly authorised Org A patient-key/report scope.
6. Patient-journey report is denied if any one of Hospital, Laboratory, or Bioinformatics report grants is missing.
7. Clinical Trials records are not returned by the operational patient-journey report.
8. Unverified or conflicting links never appear as verified patient journeys.
9. A viewer cannot mutate data; unauthorized domain reads/writes fail closed.
10. Synthetic source payload values remain unchanged; JLIGHT does not write back to source systems.
11. Cross-organization access returns no data and does not disclose whether another organization's patient exists.
12. Staging database contains only clearly labelled synthetic fixtures; production row counts and configuration remain untouched.

## Provisioning sequence

1. Confirm the staging API's `SUPABASE_URL` and `DATABASE_URL` both point to staging. Do not infer this from the Render hostname or frontend HTML. If the deployment environment cannot be inspected safely, stop live tests.
2. Create User A and User B in Supabase Auth for staging using non-production test email addresses controlled by the project owner. Do not store passwords in GitHub.
3. Create two staging organizations and memberships, then add explicit domain permission rows. Use the existing RLS-safe migration/schema; do not insert around RLS with an application token.
4. Create the minimal synthetic patient key/source-record/link fixtures only through a reviewed staging-only setup path. Require an explicit `patient_link_verified=true` plus a synthetic patient key for verified-link tests.
5. Obtain short-lived access tokens for the two test users through Supabase Auth; store them only as GitHub Actions secrets.
6. Set these repository secrets: `JLIGHT_STAGING_BASE_URL`, `JLIGHT_STAGING_USER_A_TOKEN`, `JLIGHT_STAGING_USER_B_TOKEN`, `JLIGHT_STAGING_ORG_A`, and `JLIGHT_STAGING_ORG_B`.
7. Run the manual `JLIGHT Live API Authorization (Staging Only)` workflow. Review all checks before considering staging validation passed.
8. Revoke test sessions/delete synthetic Auth users and remove only the labelled staging fixtures after evidence is captured, if cleanup is required. Never run cleanup against production.

## Current limitation

The live workflow is a read-only probe, not a fixture provisioner. Staging currently has zero organization memberships, so valid-user tests cannot pass until the synthetic Auth users and their staging memberships/permissions have been provisioned. No test tokens or user passwords belong in source control.
