# JLIGHT staging security and release review — 30 October 2026

**Environment:** Supabase project `ampkysrzliwjtvbigsvu` (`jlight-priority1-staging`) and GitHub PR #69 head `feat/visible-jc-agent`.  
**Production boundary:** `main`, production Supabase, and production deployment have not been changed.

## Executive position

The staging implementation now supports initial multi-path organisation registration, entitlement-based workspace discovery, member-scoped access, and separate JLIGHT Platform Administration approval for additional pathways. Transactional synthetic tests passed for the critical database paths.

**Production release remains blocked.** The latest staging work removes the obsolete PIN path and raw-sequence analyser API, and the Netlify preview has passed a read-only browser smoke test for white/multicolour UI and multi-path initial registration. The latest full regression run still needs to be green on the newest branch head; a prior run caught a test-harness assertion-order defect, which has been corrected. These checks do not replace authenticated email-code E2E, the complete semantic/adversarial review of SECURITY DEFINER functions, or the remaining release gates below. No system can be certified “unhackable”; this review records specific controls and evidence, not a guarantee of invulnerability.

## Approved organisation model

- An organisation registers once and selects one or more of Hospital, Laboratory, Bioinformatics, and Clinical Trials.
- The initial selection creates only those organisation-level entitlements.
- Initial registration is an organisation-declared selection of one or more pathways. The RPC validates verified identity, organisation name, allow-listed pathway keys, duplicate selections, and registration uniqueness. No additional pathway-specific evidence criteria are imposed because none were specified in the approved initial-registration model. Later pathway additions require independent Platform Administrator review. Clinical Trials recruitment remains separately governed by study-level authorisation, ethics approval and human screening.
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
| `20261030233043` | Enforce independent Platform Admin recruitment review, active Clinical Trials entitlement, active-study status and active-study referral creation |
| `20261030233959` | Restore the separate Clinical Trials read permission requirement on Hospital-to-Trial referrals; entitlement alone is not member authorisation |

All listed migrations are applied to staging. Repository filenames are aligned to the applied versions.

## Verified database controls

- `jl_organisation_workspaces`, `jl_workspace_access_requests`, and `jl_workspace_access_request_events` have RLS enabled and forced.
- Direct SELECT is denied to `anon` and `authenticated` on those tables.
- `jl_platform_admins` has RLS enabled and no direct client SELECT grants.
- Staging inspection of 25 public SECURITY DEFINER functions reported **zero anon-executable functions**. Twenty are executable by authenticated users as application RPCs; five are internal/non-client functions. The twenty callable functions still require individual semantic and adversarial review.
- Security-definer search paths are pinned. Trigger validation functions with `pg_temp` in their search path were hardened to use explicit trusted schemas.
- Fresh Supabase security advisor results: 6 RLS-enabled/no-policy INFO notices, 36 authenticated SECURITY DEFINER warnings and 1 leaked-password-protection warning. Direct privilege inspection confirms all six no-policy tables deny authenticated SELECT/INSERT/UPDATE/DELETE; the two private-schema tables also deny authenticated schema USAGE. These are closed-by-default tables accessed only through reviewed RPCs, not evidence of direct table exposure.
- Static triage of the 36 authenticated-callable SECURITY DEFINER functions confirms all have pinned `search_path` settings. Thirty-four bodies reference `auth.uid()` directly. The remaining two public wrappers delegate to private functions that explicitly require `auth.uid()` and Clinical Trials write permission or JLIGHT Platform Admin authority. This is not a substitute for function-by-function semantic and adversarial review; that review remains open.
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
- Frontend inline JavaScript syntax check: passed on the latest index.html deployment.
- Bioinformatics now has dedicated TB Intelligence compartments for overview, drug resistance, lineage, variant evidence, and QC/provenance. Completed TBProfiler JSON and JLIGHT-normalized `bioRuns` CSV are supported; imports require server-verified Bioinformatics write permission. No patient identity is inferred from a genomic run accession.
- Read-only browser smoke test: confirmed white background, white card, four distinct pathway accents, no PIN/password prompt, and simultaneous Hospital + Laboratory selection under one organisation. No email or registration request was submitted.
- The safe-regression workflow on the preceding head passed, then the next run failed only because the newly added regression guard called `require()` before its definition. That test-order defect has been corrected; the rerun on the latest head is pending.
- Authenticated Supabase RLS gate passed on the preceding application commit. The staging migration `20261031000200` is now applied, and a new regression test denies recruitment authorisation when a platform administrator is a member of the study's organisation; its latest authenticated staging run is in progress.
- Netlify preview URL: https://deploy-preview-69--jlight-health.netlify.app. Latest preview UI has been visually and interactively checked.
- Supabase automatic preview: skipped because the Git branch is not associated with a Supabase Branch; migrations were applied directly to the verified staging project.

## Remaining release gates

1. Complete authenticated email-code browser E2E for organisation registration and sign-in, invitation acceptance, workspace selection/switching, member permissions, Platform Admin approvals and tenant isolation.
2. Complete adversarial tests for the 36 authenticated SECURITY DEFINER RPCs: cross-tenant IDs, forged metadata/headers, inactive and revoked memberships, invalid roles, privilege escalation, and Clinical Trials boundaries.
3. Revalidate patient matching, patient journey reports, issue-resolution history, report permissions, worker/sequence-data controls, and Clinical Trials data isolation.
4. Confirm Supabase Auth password-provider configuration is disabled while retaining passwordless email-code UX; document the leaked-password-protection warning appropriately.
5. Complete the public South African TB dataset validation using the separately governed TBProfiler environment, preserve the two public run outputs and provenance, and import the externally generated, versioned outputs into JLIGHT. Do not reintroduce raw-sequence analysis endpoints into JLIGHT.
6. Make a separate explicit production release decision only after all gates pass.

## TB Intelligence implementation and public-data validation

- The Bioinformatics workspace now has five dedicated TB compartments: overview, drug resistance, lineage, variant evidence, and QC/provenance.
- The supported inputs are completed TBProfiler `.results.json` files and the JLIGHT-normalized `bioRuns` CSV. The importer previews and validates data, requires server-derived Bioinformatics write permission online, stores in the organisation-scoped `bioRuns` domain, and does not link sample accessions to patients.
- The isolated TBProfiler 6.7.0 environment now installs with Python 3.10. The public-data workflow records the pipeline/database versions and is attempting two public paired-end runs from `PRJEB57919` (`ERR10610053`, `ERR10610083`). The independent published-reference fixture job passed, checking the two source summaries, variant evidence, provenance and low-coverage safeguard. The separate raw-read job has not yet completed the downloads, TBProfiler execution, normalization, or artifact publication; do not report those steps as passed.
- Public TBProfiler pages for the two run accessions were independently inspected. `ERR10610053` reports median coverage 48x, lineage 2.2.2, and Pre-XDR-TB. `ERR10610083` reports median coverage 12x, lineage 4.7, and a sensitive genotype call, with an explicit warning that coverage is below 30x and some mutations may be missed. These are source-reported public outputs, not phenotypic DST or clinical truth labels.

## Clinical Trials recruitment approval hardening

- Recruitment approval is restricted to an independent JLIGHT Platform Administrator who did not create the study and is not an active member of the study organisation.
- The study must already be active, and the organisation must have an active Clinical Trials entitlement before recruitment can be authorised.
- Hospital-to-Trial referral creation requires both Hospital write and Clinical Trials read permission, an active Clinical Trials entitlement, an active study, ethics approval, a criteria-version match, a minimum-necessary candidate summary and restricted identity-link creation. A Hospital-only member cannot create a referral merely because the organisation has a Clinical Trials entitlement.
- These are staging-only additive migrations. They do not change production. Authenticated regression tests cover own-organisation denial, independent approval success, non-active-study denial, and denial of Hospital-to-Trial referral creation for a Hospital-only member without Clinical Trials read permission.

## Explicitly not done

- No merge to `main`.
- No production database migration or production data mutation.
- No production deployment.
- No destructive removal of legacy schema or code before compatibility tests.
- No password-based authentication added; JLIGHT remains passwordless email-code authentication.


## Architecture alignment note

PR #69 is an implementation branch, not the product specification. The approved JLIGHT model is one organisation identity with one or more explicitly entitled operational workspaces; it is not a one-organisation-per-pathway or one-active-path-only design. Member permissions are independently scoped within each entitled workspace. The routine-care Patient Journey is a governed linkage layer across Hospital, Laboratory and Bioinformatics, not another workspace. Clinical Trials remains a separately permissioned research domain with a restricted Hospital-to-Trial recruitment link, study-specific participant identity, consent-controlled lifecycle and auditable linkage. Preserve working legacy compatibility until dependencies and regression evidence support safe removal. The intelligence roadmap remains data ingestion/interoperability, deterministic and governed analytical processing, evidence/provenance-backed Decision Cards, and authorised human review; JC is not to be represented as a substitute for this full intelligence architecture.
