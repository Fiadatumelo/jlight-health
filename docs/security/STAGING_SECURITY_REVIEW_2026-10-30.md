# JLIGHT staging security and release review — 30 October 2026

**Environment:** Supabase project `ampkysrzliwjtvbigsvu` (`jlight-priority1-staging`) and GitHub PR #69 head `feat/visible-jc-agent`.  
**Production boundary:** `main`, production Supabase, and production deployment have not been changed.

## Executive position

The staging implementation now supports initial multi-path organisation registration, entitlement-based workspace discovery, member-scoped access, and separate JLIGHT Platform Administration approval for additional pathways. Transactional synthetic tests passed for the critical database paths.

**Production release remains blocked.** GitHub regression and authenticated RLS workflows are still pending; full browser/end-to-end validation and the complete semantic review of authenticated SECURITY DEFINER functions remain outstanding. No system can be certified “unhackable”; this review records specific controls and evidence, not a guarantee of invulnerability.

## Approved organisation model

- An organisation registers once and selects one or more of Hospital, Laboratory, Bioinformatics, and Clinical Trials.
- The initial selection creates only those organisation-level entitlements.
- **Eligibility policy gap:** the current staging RPC verifies the email, organisation name, allow-listed path keys, duplicate selections, and registration uniqueness, but it does not yet validate role-specific eligibility evidence. The required criteria/evidence for each pathway have not been formally supplied, so this must be agreed and implemented before production release.
- A later pathway request remains pending and grants no access.
- Only an independent JLIGHT Platform Administrator may approve or reject the request.
- A platform administrator cannot review a request they submitted or one from an organisation where they hold active membership.
- Email-code verification authenticates identity. It does not create membership or grant workspace access.
- Workspace discovery returns only the intersection of active organisation entitlements and the caller's active membership permissions.
- Clinical Trials remains separately permissioned and tenant-isolated.
- Organisation codes are identifiers, not credentials or access grants.

## Staging migrations applied

| Supabase migration version | Purpose |
|---|---|
| `20261030165517` | Remove anonymous execution from sensitive organisation/trial RPCs |
| `20261030165603` | Add organisation workspace entitlements and additional-path requests |
| `20261030170208` | Require active workspace entitlement and member permission |
| `20261030172115` | Multi-path registration, workspace discovery, and Platform Admin request workflow |
| `20261030172448` | Restrict multi-path classification to trusted registration |
| `20261030172537` | Preserve legacy role compatibility while making entitlements authoritative |
| `20261030172630` | Preserve owner access when an additional pathway is approved |
| `20261030172938` | Scope invitations to entitled pathways |
| `20261030173252` | Scope organisation-admin permission management to a requested domain |
| `20261030173402` | Reject legacy invitations without explicit workspace scope |
| `20261030173550` | Serialize first-time registration to prevent concurrent duplicate organisations |
| `20261030173917` | Pin trigger search paths and require verified auth in the legacy registration wrapper |
| `20261030173943` | Prevent Platform Admin self-review and own-organisation review |
| `20261030174607` | Enforce Clinical Trials-specific membership in multi-path organisations; require Laboratory entitlement in legacy Lab code resolution |
| `20261030174807` | Require an explicit workspace domain for legacy member-access listings on multi-path organisations |
| `20261030194237` | Require active Laboratory entitlement and caller Laboratory read permission when resolving an organisation by code |

All listed migrations are applied to staging. Repository filenames are aligned to the applied versions.

## Verified database controls

- `jl_organisation_workspaces`, `jl_workspace_access_requests`, and `jl_workspace_access_request_events` have RLS enabled and forced.
- Direct SELECT is denied to `anon` and `authenticated` on those tables.
- `jl_platform_admins` has RLS enabled and no direct client SELECT grants.
- Staging inspection of 25 public SECURITY DEFINER functions reported **zero anon-executable functions**. Twenty are executable by authenticated users as application RPCs; five are internal/non-client functions. The twenty callable functions still require individual semantic and adversarial review.
- Security-definer search paths are pinned. Trigger validation functions with `pg_temp` in their search path were hardened to use explicit trusted schemas.
- Supabase security advisor currently reports 4 intentional RLS-enabled/no-policy INFO notices for tables with no anon/authenticated table grants, plus 20 authenticated SECURITY DEFINER warnings and the leaked-password-protection warning. The 20 RPCs are individually guarded by caller identity/role checks, but full adversarial review remains open.
- JLIGHT's product flow uses passwordless email codes, but the Supabase Auth password-provider configuration could not be verified through the available project metadata. Do not treat the leaked-password-protection warning as not applicable until password sign-in is confirmed disabled; otherwise enable leaked-password protection without adding password-based JLIGHT sign-in.
- The legacy `jl_create_organisation` wrapper now performs its own authentication check and delegates to the validated multi-path registration transaction.

## Transactional synthetic tests performed on staging

All fixtures used synthetic accounts and were rolled back; no real patient or participant data was used.

1. Registered a synthetic organisation with Hospital, Bioinformatics, and Clinical Trials selected. Discovery returned exactly those three pathways; Laboratory remained denied.
2. Submitted an additional Laboratory request. The pending request did not grant access.
3. Confirmed a normal organisation owner could not approve a pending request.
4. Confirmed an independent Platform Super Admin could approve the request; the entitlement and owner access were then active.
5. Confirmed a Platform Admin who was also the requesting organisation owner could not review their own organisation's request.
6. Invited a synthetic member to Bioinformatics. After email-code identity and invitation acceptance, the member could access Bioinformatics only; Hospital and Clinical Trials remained denied.
7. Changed the member's Bioinformatics grant to read-only. Read remained allowed and write/report were denied.
8. Confirmed the organisation-admin domain-access listing and permission update RPCs work against a multi-path organisation.
9. Confirmed a Bioinformatics-only member in an organisation that also has Clinical Trials sees Bioinformatics only, cannot read Clinical Trials, and is not included in the Clinical Trials member listing.
10. Confirmed an organisation with the legacy Laboratory role placeholder but no active Laboratory entitlement cannot be resolved as a Laboratory organisation.
11. Hardened Laboratory organisation resolution further: the caller must also have active Laboratory read permission; the organisation code itself is not an access credential.
12. Hardened the legacy one-argument member-list RPC: it now fails closed when multiple standard pathways are active and requires an explicit workspace domain.
13. Confirmed Platform Administrator status alone does not grant organisation workspace discovery or patient-data access.
14. Confirmed an unverified email account cannot register an organisation and an organisation code alone cannot create membership.

These are targeted database tests. They do not establish that every RLS policy, API route, browser interaction, or authenticated SECURITY DEFINER function is secure.

## Application and CI state

- Frontend initial registration now supports selecting multiple pathways.
- Sign-in retains the existing passwordless email-code flow; the selected workspace is checked after verification.
- The frontend uses the server-side workspace discovery RPC instead of trusting `jl_organisations.type` as the only path.
- A separate Platform Administration view is available to verified platform super administrators for pending additional-path reviews.
- Organisation Admin Center requests an additional pathway and manages member permissions against the currently selected entitled workspace.
- Generic unscoped `reviewer` and `read_only` invitations have been removed from the UI and are rejected by the invitation RPC until a per-workspace invitation scope exists.
- Frontend inline JavaScript syntax check: passed.
- GitHub `regression` workflow: passed on commit `0e6fc6012660b5351fab5d4a00e18ee2e0beea32`; inline JavaScript, frontend contract, patient-journey privacy, CSV parser, interoperability, API/JC security, and analytical engine regression steps all passed.
- GitHub `authenticated-rls` workflow: passed on the same commit; authenticated tenant, patient-match, report-permission, and Clinical Trials isolation tests passed.
- Netlify: the latest PR commit's redirect/header/page checks completed as neutral (no redirect/header rules configured; one asset changed). The deploy preview is still processing at https://app.netlify.com/projects/jlight-health/deploys/6ae4d937b05a356e46da97ec.
- Supabase automatic preview: skipped because the Git branch is not associated with a Supabase Branch; migrations were applied directly to the verified staging project.

## Remaining release gates

1. Define and implement the eligibility criteria/evidence requirements for each initial-registration pathway; the current staging RPC does not yet enforce them.
2. Complete browser end-to-end tests for one-path and multi-path registration, email-code sign-in, invitation acceptance, path switching, member permissions, Platform Admin approvals, and organisation isolation.
3. Complete adversarial tests for the twenty authenticated SECURITY DEFINER RPCs: cross-tenant IDs, forged metadata/headers, inactive and revoked memberships, invalid roles, privilege escalation, and Clinical Trials boundaries.
4. Revalidate patient matching, patient journey reports, issue-resolution history, report permissions, worker/sequence-data controls, and Clinical Trials data isolation.
5. Re-run the Supabase security advisor and document any remaining intentional INFO notices.
6. Make a separate explicit production release decision only after all gates pass.

## Explicitly not done

- No merge to `main`.
- No production database migration or production data mutation.
- No production deployment.
- No destructive removal of legacy schema or code before compatibility tests.
- No password-based authentication added; JLIGHT remains passwordless email-code authentication.
