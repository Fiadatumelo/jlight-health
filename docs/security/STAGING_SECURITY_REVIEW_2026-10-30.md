# JLIGHT staging security review — 30 October 2026

**Environment:** Supabase project `ampkysrzliwjtvbigsvu` (`jlight-priority1-staging`)  
**Production boundary:** No production project, main branch, production database, or production deployment was changed.

## Executive result

The three anonymous-execution findings were remediated on staging and verified by PostgreSQL privilege checks:

| Function | anon EXECUTE after fix | authenticated EXECUTE | service_role EXECUTE |
|---|---:|---:|---:|
| jl_accept_organisation_invitation(uuid,text) | false | true | true |
| jl_invite_org_member(text,text) | false | true | true |
| jl_list_trial_members(uuid) | false | true | true |

Migration: `20261030165517_harden_sensitive_rpc_execution`  
Git migration: `supabase/migrations/20261030165517_harden_sensitive_rpc_execution.sql`

## SECURITY DEFINER review

The Supabase advisor continues to report 14 SECURITY DEFINER functions executable by authenticated users. This advisor finding is not proof of an exploit: these functions are intentionally called by the signed-in application and therefore cannot all have EXECUTE revoked without breaking workflows. They must nevertheless remain individually reviewed and tested.

The staging catalogue inspection confirmed that all 14 have a pinned search_path and contain an `auth.uid()` reference. This is a baseline, not a substitute for complete semantic review or adversarial testing.

| Function | Required authorisation contract |
|---|---|
| jl_accept_organisation_invitation | Verified authenticated identity; confirmed email; exact active organisation/code match; a pre-existing administrator-created invitation for that same user/org; activate only that invitation |
| jl_create_organisation | Authenticated identity; strict allow-list for initial registration paths; must not create membership or entitlement implicitly unless the same transaction establishes the owner safely |
| jl_has_org_role | Boolean-only result for the caller's own active membership and requested role |
| jl_invite_org_member | Active organisation owner/admin; organisation resolved from trusted membership; target account exists; role constrained to entitled path; no self-invite |
| jl_is_org_member | Boolean-only result for caller's own active membership in the specified organisation |
| jl_is_platform_super_admin | Boolean-only lookup for caller's own active platform-admin record; no table rows exposed |
| jl_link_user_to_organisation | Authenticated caller; valid active org/code; existing active or invited membership; invitation must be accepted before profile linking; no code-only membership creation |
| jl_list_trial_members | Active Clinical Trials owner/admin in the same organisation; returns only that organisation's trial members; must not return other tenant/member data |
| jl_resolve_lab_org | Authenticated caller; valid unambiguous code; returns identifier only; callers must still verify membership before any data access |
| jl_review_intelligence_finding | Active permitted org role plus write access to every source domain of the finding; row locked before update; allowed actions only |
| jlight_finding_domain_access | Caller identity; finding/org match; valid access type; all source observations must belong to same org and caller must have required access to each source domain |
| jlight_has_domain_permission | Caller identity; active org; valid domain/access; active membership and domain permission; Clinical Trials separately gated |
| jlight_list_org_domain_access | Active owner/admin of the same org; returns only that organisation's members and permission assignments |
| jlight_set_member_domain_permission | Active owner/admin; target is active member of same org; domain is allowed; write/report imply read; no self-escalation by non-owner |

### Mandatory follow-up from multi-workspace design

The permission helper has now been replaced on staging with an entitlement-aware implementation. It requires an active organisation, an active entitlement for the requested workspace, and the caller's active membership plus member-level permission. Clinical Trials uses its separate `jl_org_memberships` roles. Platform-admin status alone no longer grants patient-data access.

The application/API still contains single-path resolution and must be migrated before multi-workspace registration is enabled. Platform-admin review actions must use a separate explicit platform-admin authorisation path.

Also review `jl_invite_org_member`, `jl_link_user_to_organisation`, `jl_list_trial_members`, and `jlight_set_member_domain_permission` against the new entitlement relation before enabling multi-path registration.

## Platform administrator table

Staging catalogue inspection found:

- RLS enabled on `public.jl_platform_admins`.
- No direct RLS policies.
- No SELECT privilege for `anon` or `authenticated`.
- SELECT available to `service_role`.
- Authenticated application code reads the table only through the narrow boolean helper `jl_is_platform_super_admin()` (SECURITY DEFINER, caller-scoped to `auth.uid()`).

This is an intentional deny-by-default design. A direct client-facing policy would unnecessarily expose privileged role assignments. The advisor's `rls_enabled_no_policy` notice is therefore documented as intentional, not fixed by adding a broad policy.

## New entitlement tables

Staging additive migration `20261030191000_add_organisation_workspace_entitlements` created:

- `jl_organisation_workspaces`
- `jl_workspace_access_requests`

Both have RLS enabled and forced, and direct table privileges revoked from PUBLIC, anon, and authenticated. Only service_role has direct table privileges; application access must be mediated by reviewed RPCs.

Observed staging result:
- 1 existing organisation entitlement safely backfilled from its unambiguous legacy Laboratory path.
- 0 additional-path requests.
- No existing organisation data or legacy columns were deleted or rewritten.

Supabase advisor reports RLS-enabled/no-policy INFO notices for these two tables and `jl_platform_admins`. This is intentional until secure RPC-mediated access is implemented. Do not add permissive direct policies merely to silence the advisor.

## Latest staging hardening — 30 October 2026, 17:02 UTC

### Entitlement-aware permission function

Migration: `20261030170208_entitlement_aware_domain_authorization`  
Git source: `supabase/migrations/20261030170208_entitlement_aware_domain_authorization.sql`  
Git commit: `02e872179a0e93b8603417accba632ea499bc8b8`

The helper now fails closed unless the organisation is active, the requested workspace has an active row in `jl_organisation_workspaces`, and the caller has an active membership plus the required member permission. Clinical Trials remains checked through its separate membership roles. The former platform-admin patient-data bypass was removed.

Staging checks:
- Existing organisation owner + existing Laboratory entitlement: Laboratory read = true.
- Hospital without an entitlement: false.
- Bioinformatics without an entitlement: false.
- Clinical Trials without an entitlement: false.
- Synthetic unauthorised user with a forged subject context: false.
- PostgreSQL privilege audit across all 19 public SECURITY DEFINER functions: 0 executable by anon; 14 executable by authenticated.

These checks prove the tested permission boundary only. They do not prove all authenticated RPCs, all RLS policies, all API routes, or browser flows are secure.

### PR #69 release blocker

A review comment was added to [PR #69](https://github.com/Fiadatumelo/jlight-health/pull/69). A formal REQUEST_CHANGES review cannot be submitted by the PR author, so the blocking findings were recorded as a PR conversation comment.

The current PR still states that each organisation has one registered path and its frontend/API resolve a single `jl_organisations.type`. It does not yet implement the approved multi-path registration, entitlement discovery, or platform-admin additional-path decision workflow. The separate authenticated Supabase RLS workflow has no run recorded for the current staging hardening commit. The safe-regression workflow success is not a substitute for authenticated database tests.

### Current advisor interpretation

- Anonymous SECURITY DEFINER warning: resolved; zero anon-callable functions across the 19 inspected public SECURITY DEFINER functions.
- Authenticated SECURITY DEFINER warning: 14 remain; intended app RPCs/helpers, but individual adversarial testing is still required.
- RLS enabled without policy: 3 INFO notices (`jl_platform_admins`, `jl_organisation_workspaces`, `jl_workspace_access_requests`). These are intentionally non-client-accessible and have no anon/authenticated table grants. Do not add broad policies.
- Leaked-password protection: advisor warning remains. JLIGHT uses passwordless email-code authentication; do not introduce passwords to clear an unrelated password-protection lint.

## Remaining release blockers

1. Complete semantic and adversarial tests for all 14 authenticated SECURITY DEFINER functions, including cross-tenant IDOR, forged metadata/header, inactive membership, revoked membership, invalid role, and Clinical Trials boundary tests.
2. Replace the single-path frontend/API scope resolver with entitlement-aware workspace discovery and per-request workspace validation.
3. Add and test secure RPCs for initial multi-path registration, workspace discovery, additional-path request submission, and platform-admin-only review/approval.
4. Test the platform-admin registry cannot be read or modified by anon/authenticated direct table access; test the helper cannot be forged by user metadata.
5. Re-run Supabase security advisors. Expected residual INFO notices for intentionally policy-less, non-client-accessible tables must be explicitly documented. Any anonymous SECURITY DEFINER finding is a release blocker.
6. Resolve the leaked-password-protection advisor in the context of JLIGHT's passwordless email-code authentication: confirm password sign-in is disabled/not used, and document the advisor as not applicable if so. Do not introduce passwords to silence it.

## Verification references

Supabase advisor remediation:
- https://supabase.com/docs/guides/database/database-linter?lint=0028_anon_security_definer_function_executable
- https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable
- https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy

**Status:** Three anonymous execution warnings resolved and verified. Platform-admin table lockdown verified as intentional. Fourteen authenticated SECURITY DEFINER functions remain under release review; the system is not certified release-ready.
