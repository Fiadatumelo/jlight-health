# JLIGHT Organisation Registration and Workspace Entitlements

**Status:** Approved design specification  
**Scope:** Staging implementation only  
**Production:** No production code, schema, data, configuration, or deployment changes are authorised by this document.

## 1. Locked business rules

1. An organisation completes one initial registration.
2. During initial registration, it may select **one or multiple** JLIGHT pathways:
   - Hospital
   - Laboratory
   - Bioinformatics
   - Clinical Trials
3. The selected initial pathways are recorded as organisation-level workspace entitlements after the applicable registration and eligibility checks pass.
4. An organisation cannot self-enable a pathway after initial registration.
5. Every post-registration pathway addition is a request requiring eligibility review and an explicit decision by **JLIGHT Platform Administration**.
6. Organisation administrators may manage members and their access only within pathways already entitled to their organisation. They cannot approve or create organisation-level pathway entitlements.
7. A user's email-code sign-in authenticates identity; it does not grant organisation membership or pathway entitlement.
8. JLIGHT resolves the organisation and authorised workspaces from trusted database records. Browser selections, user-editable metadata, local storage, and request headers are never authoritative.
9. Clinical Trials remains a separately permissioned and data-isolated workspace even when selected alongside other pathways.

## 2. Registration flow

1. User enters organisation details and verified contact email.
2. User selects one or more pathways in the initial registration form.
3. JLIGHT validates the selection and runs the applicable organisation/path eligibility checks.
4. JLIGHT creates the organisation record and one entitlement record per approved initial pathway in a single transaction.
5. JLIGHT creates the organisation code and the initial organisation-administrator membership/invitation using the existing secure, passwordless email-code flow.
6. After email-code verification and invitation/membership validation, the user is shown only the organisation's active, approved pathways.
7. The user selects a workspace to enter. The server rechecks active membership, entitlement, workspace permission, and organisation status before returning data.

Registration must fail closed: partial organisation creation or partial entitlement provisioning must not leave an organisation with an ambiguous or unintended set of workspaces.

## 3. Post-registration additional-path workflow

1. An authorised organisation administrator submits an additional-path request with the required eligibility evidence.
2. JLIGHT stores the request as `pending_review`; the requested pathway is not accessible while pending.
3. JLIGHT Platform Administration reviews the organisation's eligibility against the pathway's current criteria.
4. An administrator records an explicit approve/reject decision, reviewer identity, timestamp, rationale, and criteria/version reference.
5. Approval creates or activates the organisation-path entitlement. Rejection creates no entitlement.
6. The organisation administrator is notified of the decision.
7. On the next workspace discovery/refresh, eligible members can see the newly approved pathway, subject to member-level permissions.
8. Repeated requests for an already active pathway are rejected as duplicates or returned as already entitled; they must not create duplicate entitlements.

Only a JLIGHT platform-administration permission may approve or reject these requests. Organisation-level owner/admin roles must not satisfy that permission.

## 4. Data model direction

Use a normalised, organisation-to-workspace entitlement model rather than treating a single `jl_organisations.type` value as the complete authority.

### 4.1 Organisation workspace entitlements

Introduce a relation such as `jl_organisation_workspaces` with:

- `id`
- `org_id` (FK to `jl_organisations`)
- `workspace_key` (constrained to `hospital`, `laboratory`, `bioinformatics`, `clinical_trials`)
- `status` (at minimum `active` or `revoked`)
- `provisioning_source` (`initial_registration` or `admin_approval`)
- `approved_by` (nullable for eligible system-provisioned initial registration; required for post-registration additions)
- `approved_at`
- `created_at`, `updated_at`

Enforce uniqueness for the organisation/workspace pair. Entitlement state must be read from this relation, not inferred from client state or user metadata.

### 4.2 Additional-path requests

Introduce a relation such as `jl_workspace_access_requests` with:

- `id`, `org_id`, `requested_workspace`
- `status`: `pending_review`, `approved`, `rejected`, `withdrawn`
- `eligibility_evidence` or a secure evidence reference (do not place sensitive evidence in audit text)
- `criteria_version`, `eligibility_result`
- `submitted_by`, `submitted_at`
- `reviewed_by`, `reviewed_at`, `decision_reason`

Prevent multiple unresolved requests for the same organisation/workspace pair. Keep a durable decision history; do not overwrite the audit trail when a request is resubmitted.

### 4.3 Existing organisation type

The existing singular `jl_organisations.type` / legacy role fields may be retained temporarily for compatibility and migration/backfill only. They must not be used as the sole source of truth for multi-workspace authorisation. Do not destructively remove or reinterpret legacy values until all callers, policies, reports, and existing organisations have been migrated and regression-tested.

## 5. Authorisation and isolation

Every workspace request must be authorised server-side against all of:

- authenticated user identity from the verified session/token;
- active organisation membership;
- active organisation status;
- active organisation entitlement for the requested workspace;
- active member permission for the requested workspace and operation;
- workspace-specific data scope and row-level security.

The API must derive `org_id` and workspace scope from trusted database membership/entitlement records. Ignore client-supplied organisation IDs, roles, workspace names, `X-Role` headers, and editable user metadata for authorisation.

Clinical Trials must retain its separate permission domain, endpoint allow-list, participant-identifier protections, audit controls, and data isolation. Multi-workspace entitlement must never imply cross-workspace patient/participant record access.

## 6. Sign-in and workspace discovery

Keep the existing passwordless email-code authentication. Do not introduce passwords or require users to choose an organisation pathway before identity verification.

After email-code verification:
- resolve the user's active memberships;
- resolve each organisation's active workspace entitlements;
- intersect those entitlements with the user's active workspace permissions;
- display the resulting available workspaces;
- require a fresh server-side authorisation check when a workspace is opened.

If the user belongs to multiple organisations, show the organisations they are actively a member of, then the permitted workspaces for the selected organisation. Do not silently select a workspace based on stale browser state.

## 7. Staging implementation sequence

1. **Inventory:** identify every frontend, backend, RPC, SQL policy, invitation flow, report, and test that reads `jl_organisations.type` or assumes one organisation equals one path.
2. **Schema design/migration:** add the entitlement and request relations, constraints, indexes, audit fields, and least-privilege RLS. Backfill each existing organisation's current verified path as its initial entitlement without widening access.
3. **Registration:** update the initial registration UI and transaction to accept a non-empty set of selected paths and provision all approved initial entitlements atomically.
4. **Workspace discovery:** replace single-path resolution with membership + entitlement + member-permission intersection after passwordless sign-in.
5. **Additional-path administration:** implement request submission and a platform-admin-only review/decision workflow. Organisation admins may submit requests but cannot approve them.
6. **Backend enforcement:** update API scope resolution and RPCs to require an active entitlement for the requested path. Fail closed on missing, revoked, or ambiguous records.
7. **RLS and security:** enforce tenant and workspace scope at the database layer; preserve the Clinical Trials boundary.
8. **Compatibility cleanup:** remove single-path assumptions only after references are migrated and tests prove the new model. Retain safe compatibility reads during transition; do not run broad destructive cleanup.
9. **Validation:** run registration, multi-path discovery, additional-path approval/rejection, invitation, member permission, tenant isolation, revocation, and Clinical Trials isolation tests using synthetic staging data.
10. **Staging acceptance:** verify the preview and staging database independently. Record migration versions, test evidence, and unresolved risks. Do not merge to `main`, merge a Supabase branch to production, or deploy production as part of this work.

## 8. Required acceptance tests

- Initial registration with exactly one pathway creates exactly one active entitlement.
- Initial registration with two or more pathways creates exactly those active entitlements and no others.
- Empty or invalid path selection is rejected.
- Registration transaction failure leaves no partially provisioned organisation/entitlement state.
- Email-code authentication alone does not grant membership or workspace access.
- Workspace discovery shows only the intersection of active organisation entitlements and member permissions.
- A member cannot access an unassigned or revoked pathway by changing browser state, API payload, URL, metadata, or headers.
- An organisation administrator can submit an additional-path request but cannot approve it.
- A pending request grants no access.
- Only a platform administrator with the dedicated permission can approve/reject.
- Approval grants only the requested pathway; rejection grants nothing.
- Duplicate pending requests and duplicate entitlements are prevented.
- Revoking an entitlement immediately blocks new requests and workspace discovery.
- Existing single-path organisations retain their existing access after backfill.
- Clinical Trials remains isolated from Hospital, Laboratory, and Bioinformatics data and permissions, including for multi-path organisations.
- Passwordless email-code sign-in, organisation codes, invitations, and existing membership controls continue to work.

## 9. Explicit non-goals and safety boundaries

- No password-based authentication redesign.
- No organisation-code-as-membership shortcut.
- No organisation-admin self-approval of additional pathways.
- No implicit access to all pathways because an organisation has multiple entitlements.
- No relaxation of Clinical Trials controls.
- No production schema migration, production data mutation, merge to `main`, or production deployment.
- No removal of legacy columns/tables until a separate compatibility and migration review approves it.

## 10. Staging-only completion definition

The design is ready for implementation when the schema migration plan, registration transaction, entitlement resolver, platform-admin approval permission, RLS policies, compatibility/backfill plan, and acceptance tests have been reviewed together. Staging implementation is complete only when all acceptance tests pass against the staging database and preview. Production remains untouched and requires a separate explicit release decision.
