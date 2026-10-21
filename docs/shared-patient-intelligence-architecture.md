# JLIGHT Shared Patient Intelligence Architecture
**Status:** Proposed implementation plan  
**Owner:** JLIGHT  
**Purpose:** Connect authorised hospital, laboratory, and bioinformatics workflows around one patient identity while keeping clinical research governance separate.

## Product architecture

### 1. Connected care modules
- **Hospital Operations** is the clinical entry point: patient identity, encounters, admissions, diagnoses, observations, medication context, and clinical orders.
- **Laboratory Intelligence** manages orders, specimens, results, QC, release status, and laboratory-specific investigations.
- **Bioinformatics** analyses authorised sequence, genomic, microbiology, and other permitted datasets. It references the same patient identity only when the use is authorised and clinically appropriate.
- **Cross-Section Intelligence** correlates events across the three care modules and creates explainable review alerts. It must preserve source records and never silently overwrite a clinical result.

### 2. Separate Clinical Trials product area
Clinical Trials must be separated from routine care at the permission and data-governance level. It contains:
- **Clinical Trial Management System (CTMS):** studies, sites, milestones, monitoring, teams, and study-level deviations.
- **Clinical Trial Site:** screening, eligibility, informed consent, enrolment, participant visits, source records, and protocol compliance.
- **Clinical Data Management System (CDMS):** eCRFs, validation rules, discrepancies, data queries, query resolution, audit history, and database-lock readiness.
- **Clinical Trial Laboratory:** protocol-specific test schedules, specimens, chain of custody, QC, results, and reconciliation with study data.

A study may link to relevant routine-care or laboratory records only when the protocol, legal basis, permissions, and consent/authorisation allow it. Trial participants and routine-care patients must not be automatically merged based only on name or email.

## Core design rules

1. **One internal patient identifier** per resolved patient, with a controlled identity-matching workflow and duplicate review. Do not use name, email, or national ID as the cross-module primary key.
2. **Shared patient/encounter references, separate domain records.** Laboratory results, hospital encounters, and bioinformatics runs remain source-owned records linked by stable IDs.
3. **Explainable findings.** Each cross-section alert records the rule/model version, evidence references, timestamps, severity, uncertainty, and reviewer disposition.
4. **Human review.** Alerts are potential discrepancies, not diagnoses or proof of an incorrect result. No automatic clinical decisions or silent correction of source data.
5. **Role-based access enforced by the database/API**, not merely hidden UI controls. Keep Supabase RLS enabled; never solve access errors by making patient data public.
6. **Auditability.** Record access, exports, record linking/unlinking, result review, query resolution, and alert acknowledgement. Protect audit records against unauthorised edits.
7. **Privacy by design.** Minimise patient data, use pseudonymous trial identifiers where appropriate, define retention, and validate the design against POPIA and applicable clinical-research requirements.
8. **Shared identity is not universal access.** A user may switch modules without being forced to create a new account, but the backend must authorise each module and record independently.

## Suggested data model (to be mapped to the existing Supabase schema before migration)

- jl_patients: internal patient ID, organisation/tenant, demographic matching fields with minimisation, status, created/updated timestamps.
- jl_patient_identifiers: patient ID, identifier type, issuer, protected identifier value/reference, verification status, effective dates; unique constraints scoped to issuer and tenant.
- jl_encounters: patient ID, facility, encounter type, start/end time, status.
- Existing laboratory tables: patient ID and encounter ID foreign keys where appropriate.
- Existing hospital tables: patient ID and encounter ID foreign keys where appropriate.
- Existing bioinformatics tables: patient ID and source specimen/result references only where authorised.
- jl_cross_section_findings: tenant, patient ID, encounter ID (nullable), finding type, severity, explanation, evidence references, rule/model version, status, reviewer and timestamps.
- Clinical research tables: study, site, participant, consent/authorisation, visit, eCRF/data query, specimen, and trial-lab result; separate permissions and study-specific pseudonymous participant identifiers.
- jl_audit: append-oriented audit events with actor, action, resource, timestamp, and appropriate integrity controls.

These are target concepts, not instructions to create tables blindly. Confirm current columns, foreign keys, indexes, RLS policies, grants, and existing data first. Prefer additive, reversible migrations.

## Implementation phases

### Phase 0 — Stabilise authentication and workspace access
- Reproduce and diagnose the jl_organisations insert RLS error using an authenticated session.
- Inspect all policies, table columns, foreign keys, triggers, grants, and existing organisation rows.
- Fix account/workspace recovery without deleting users, dropping RLS, or weakening tenant isolation.
- Replace the current switch-workspace sign-out flow with module navigation only after the permission model is defined and tested.

### Phase 1 — Inventory and shared patient identity
- Map the existing frontend state and all Supabase tables to this architecture.
- Identify localStorage-only data and silent sync failures.
- Add stable patient and encounter links through a reviewed migration, with duplicate detection and rollback.
- Preserve existing patient records; do not auto-merge uncertain matches.

### Phase 2 — Cross-Section Intelligence
- Define deterministic checks first: missing linked orders/results, inconsistent identifiers, chronology conflicts, unacknowledged critical results, and trial/lab reconciliation discrepancies.
- Store findings with evidence and review status.
- Test with synthetic data before any real patient data.
- Add statistical/AI prioritisation only with validation, provenance, and clear uncertainty.

### Phase 3 — Clinical Trials separation
- Separate CTMS, Site, CDMS, and Trial Laboratory workflows and permissions.
- Implement study-specific pseudonymous IDs, consent/authorisation references, eCRF validation, query workflows, audit trails, and trial data reconciliation.
- Add controlled linkage to routine care only for authorised use cases.

### Phase 4 — Validation and release
- Test RLS with multiple users and tenants, cross-module access, account recovery, audit events, persistence, duplicate patients, and denied access.
- Test alert rules with synthetic known-positive and known-negative cases; document limitations and false-alert handling.
- Verify Netlify production deployment and Supabase connectivity separately. Do not claim production-ready or clinically validated until independently tested.

## Immediate known issue in current frontend

The current doSwitchWorkspace(targetRole) function saves role-specific local data, signs out of Supabase, clears the user/profile state, and sends the user to sign-in for the target role. This directly conflicts with the desired shared-patient workflow. It should be changed to module navigation only after backend authorisation checks are designed; simply removing sign-out could accidentally expose module data to users who are not authorised for it.

The current frontend also loads legacy samples, entries, cards, and audit by organisation plus STATE.role. Shared patient records therefore need an explicit identity/reference layer; changing the switch button alone will not create cross-section intelligence.

## Release acceptance criteria

- One authorised user can navigate between permitted care modules without creating a separate account for each module.
- The same patient/encounter can be referenced consistently by Hospital, Laboratory, and authorised Bioinformatics workflows.
- Cross-section alerts cite the source records and explain why the relationship is suspicious.
- A user cannot read another tenant's patients or records by changing the UI role or request payload.
- Clinical trial records are isolated by study/site permissions and only linked to routine care through an explicit authorised path.
- All changes are tested with synthetic data and migrations are reviewed before being applied to production.
