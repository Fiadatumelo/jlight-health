# JLIGHT Cross-Section Intelligence Security Foundation

## Goal
Create a tenant-isolated data foundation for linking authorised Hospital Operations, Laboratory and Bioinformatics records and producing explainable findings. Clinical Trials is a separate data domain.

## Migration
`supabase/migrations/202610220003_cross_section_intelligence_foundation.sql`

It creates explicit organisation memberships, patient and encounter references, source observations with provenance, explainable findings, review events, and separate trial studies/participants. Existing organisation owners are backfilled as owner members.

## Security model
- RLS is enabled and forced on all new tables.
- Every record is scoped to an organisation; membership and role checks use the authenticated Supabase user.
- Browser clients cannot write membership rows. A reviewed trusted-server invitation flow is required.
- Organisation codes are identifiers, not credentials; never allow code-only membership.
- Trial data uses separate tables and role-specific policies; routine roles do not automatically gain participant access.
- Findings reference source observations and are advisory; no automatic clinical decisions.
- Do not send identifiable health data to external AI providers without privacy, legal, security and vendor approval.

## Required before production
1. Verify `public.jl_organisations.id` is UUID and review live schema/policies/triggers in staging.
2. Test two organisations and multiple roles, including inactive membership, read-only, trial-only, and cross-tenant access.
3. Add automated RLS/migration tests and CI.
4. Review POPIA obligations, purpose limitation, retention, data-processing agreements, breach response and access logging.
5. Verify backups and restoration, monitoring, secret management, vulnerability scanning and independent penetration testing.
6. Build authenticated ingestion/adapters, deduplication, versioned deterministic rules, a reviewed findings UI and safe resolution workflow.
7. Use synthetic data only until all gates pass.

## Scope limitation
This is a foundational schema, not a complete commercial-ready implementation. It does not yet implement ingestion pipelines, invitations, study-specific per-user grants, dashboard integration, operational monitoring, backup verification, or clinical validation. Do not claim production readiness until those are implemented and tested.
