# JLIGHT Release Readiness — Priority 1

Status: **HOLD for production deployment pending full browser/API acceptance testing and explicit release approval.** The changes below have been applied to the isolated staging project and synthetic SQL-level tests have passed. This document does not authorize production deployment.

## Release goals

- Preserve stable organisation IDs and verified profile-based tenant resolution.
- Prevent cross-organisation patient, laboratory, hospital, and bioinformatics access.
- Route requests to an explicitly identified, active laboratory organisation.
- Keep clinical-trial access separate and limited to active Trial organisations.
- Preserve existing data and fail closed where the correct access contract is not yet defined.

## Implemented in the release branch and staging

- Added organisation/domain persistence columns to `jl_entries`; legacy rows are not auto-assigned to an organisation.
- Added `target_org_id` routing to `jl_requests`, organisation-specific sender/recipient policies, immutable request details, and guarded request state transitions.
- Updated both request synchronization paths to use stable organisation IDs rather than workspace-only routing.
- Made JLIGHT domain policies authenticated-only, revoked anonymous domain table access, and restricted dangerous table-level privileges.
- Kept profile identity, organisation, role, and activation fields out of direct browser updates; ordinary profile updates are limited to approved columns.
- Moved internal tenant helper functions into a non-exposed `private` schema.
- Restricted Trial protocol, participant, visit, consent, adverse-event, and deviation access to active Trial organisations.
- Blocked self-service Trial organisation creation and code-only Trial membership. Multi-user Trial access requires an approved provisioning flow.
- Kept seven legacy/operational tables fail-closed pending explicit product access requirements.

## Staging validation already completed

Synthetic fixtures were created only inside transactions and rolled back.

- Sender/recipient/unrelated-organisation request read and update isolation.
- Intended laboratory acceptance and result release; submitted request fields are immutable and released results cannot be changed through the tested route.
- Patient linkage across hospital admission, clinical order, laboratory order, sample, result, bioinformatics accession, and bioinformatics run.
- Cross-tenant denial for patient and result records.
- Trial-vs-Hospital separation and Trial-only protocol/participant access.
- Denial of self-service Trial organisation creation, direct Trial inserts, and code-only Trial membership.
- Catalog checks for anonymous grants, PUBLIC policies, request routing foreign key/trigger, private helper functions, Trial policies, and restricted profile/organisation UPDATE privileges.
- GitHub Actions safe regression workflow passed frontend JavaScript syntax and analytical-engine tests for the prior release head; rerun for the latest commit before release.

## Remaining release gates

1. Run and confirm automated checks for the latest release-branch commit.
2. Complete browser/API end-to-end tests using the real UI and authenticated test accounts, including signup/login, organisation creation/linking, request creation/routing/acceptance/release, patient records, consent, and the cross-section report.
3. Confirm the seven fail-closed tables (`alerts`, `audit_log`, `csv_uploads`, `decision_cards`, `jl_samples`, `profiles`, `system_health_log`) are intentionally inaccessible until table-specific policies and workflows are approved.
4. Review the three remaining SECURITY DEFINER warnings for organisation creation, membership linking, and laboratory routing.
5. Establish a controlled, auditable invitation/provisioning process for Trial collaborators.
6. Review migration order and rollback/recovery instructions before production schema changes.
7. After production deployment, create a clearly labelled synthetic user and synthetic patient, then exercise the complete intended journey. Do not use real patient information or claim clinical suitability from synthetic tests.

## Deployment sequence

- Keep the pull request unmerged until all release gates are met.
- Back up/review production schema and confirm row counts before any migration.
- Apply reviewed Supabase migrations in order in a planned maintenance/release window; do not assume a GitHub merge automatically applies database migrations.
- Deploy the static application once through Netlify after schema compatibility is confirmed; avoid repeated preview/production deploys because deploy credits are limited.
- Run synthetic smoke tests, verify no cross-tenant access, and keep a rollback plan ready.
- Production changes require explicit release-owner approval.