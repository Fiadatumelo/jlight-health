# JLIGHT Release-Hold Remediation — Review Specification

Status: **HOLD — staging validation required; do not deploy or apply these changes to production.**

This document records the mandatory corrections for the domain-persistence and tenant-hardening remediation. It is a review specification, not evidence that the SQL changes or tests have already been implemented.

## Non-negotiable safety constraints

1. Preserve the existing profile-based organisation-resolution behaviour in `jl_current_org_id()`. Do not replace it with a JWT `org_id` claim unless the existing auth/org model is deliberately migrated and proven compatible.
2. Never assign legacy `jl_entries` rows to an organisation merely because its display name matches `JLIGHT Health Intelligence Platform`. Reconcile ownership using trustworthy identifiers; leave ambiguous rows unassigned and report them for manual review.
3. Do not trust a client-supplied requested role in `jl_upsert_membership`. Role assignment must be derived and enforced server-side from verified identity, an authorised invitation or an existing authorised administrator action. A user must not be able to grant themselves `admin` or `supervisor`.
4. Keep clinical-trial access explicitly separated and authorised. Do not silently grant trial permissions through a default role or cross-section workflow.
5. Preserve existing application functionality and the current schema/auth/organisation model through incremental, backwards-compatible changes.

## Required implementation review

### A. Domain persistence migration
- Confirm all new columns, constraints, indexes, and policies are compatible with the live schema and existing rows.
- Ensure organisation identifiers are stable IDs, not display-name matches.
- Ensure writes and reads are scoped to the authenticated user's verified organisation membership.
- Make the migration re-runnable or fail safely with a clear diagnostic; avoid destructive rewrites and implicit data reassignment.

### B. Tenant-hardening migration
- Preserve the established `jl_current_org_id()` resolution path.
- Verify RLS policies prevent cross-tenant SELECT, INSERT, UPDATE, and DELETE.
- Verify membership creation cannot escalate privileges through client-provided metadata, role names, or organisation IDs.
- Audit any security-definer functions for fixed search_path, minimal grants, and explicit authorisation checks.

### C. Legacy-row reconciliation
- Produce counts for assigned, unassigned, and ambiguous legacy records before changing ownership.
- Do not bulk-update ambiguous records. Keep them unassigned pending verified reconciliation.
- Include a rollback/recovery plan and a record-level audit trail for any approved ownership changes.

## Staging acceptance gates

- [ ] Review actual migration SQL against the live schema and current migration history.
- [ ] Apply migrations only to a non-production staging database.
- [ ] Test unauthenticated access and cross-organisation reads/writes for every affected table.
- [ ] Test ordinary member, organisation administrator, supervisor, and clinical-trial permissions.
- [ ] Attempt self-promotion to `admin` and `supervisor`; both must be denied server-side.
- [ ] Test ambiguous legacy rows remain unassigned.
- [ ] Run the synthetic patient journey across laboratory, hospital/health-informatics, and bioinformatics sections; verify traceability and a coherent report. Clinical trials must remain an explicitly authorised, separate journey.
- [ ] Capture migration output, test results, RLS/security-advisor findings, and rollback evidence.

## Release decision

Production remains blocked until the actual SQL/code changes are reviewed, all staging gates pass, and a rollback plan is approved. This branch and checklist do not themselves constitute a release approval.
