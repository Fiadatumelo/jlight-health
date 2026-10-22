# JLIGHT Priority 1 — Safe Database Remediation Draft

Status: **Draft for review; not applied to any database.**  
Target branch: `fix/domain-persistence-v1`  
Purpose: remove unsafe assumptions from the original release bundle before staging validation.

## Non-negotiable safeguards

1. Do not replace `public.jl_current_org_id()` in this migration. The live policy design currently derives the organisation from `jl_user_profiles.org_id`; switching to JWT claims without confirming token configuration can break access control.
2. Do not assign unowned legacy rows to `Jlight-Health`. Ownership must be established from trustworthy evidence, row by row.
3. Do not drop the global `UNIQUE(jl_id)` constraint until duplicates, application assumptions, and tenant-scoped identifiers have been checked.
4. Do not add broad `USING (true)` policies to alerts or system-health tables. Access must be based on a defined operational role and least privilege.
5. Do not introduce a membership RPC that accepts a caller-selected privileged role. Roles must be derived from trusted server-side rules.
6. Do not run this draft against production. First inspect schema and policies, then apply to an isolated staging project or branch and test with two separate test organisations.

## Phase A — read-only preflight

Run these queries in the intended **staging** database before applying any DDL.

```sql
-- A1. Confirm jl_entries columns and constraints.
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'jl_entries'
ORDER BY ordinal_position;

SELECT c.conname, c.contype, pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
WHERE c.conrelid = 'public.jl_entries'::regclass
ORDER BY c.contype, c.conname;

-- A2. Check organisation resolver and existing policies.
SELECT pg_get_functiondef('public.jl_current_org_id()'::regprocedure);

SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN (
    'jl_entries', 'jl_patients', 'jl_lab_orders', 'jl_lab_results',
    'jl_samples', 'jl_admissions', 'jl_participants', 'jl_visits',
    'jl_consents', 'jl_deviations', 'jl_user_profiles', 'jl_organisations',
    'alerts', 'system_health_log'
  )
ORDER BY tablename, policyname;

-- A3. Count unassigned legacy records; do not modify them.
SELECT count(*) AS total_rows,
       count(*) FILTER (WHERE org_id IS NULL) AS unassigned_rows
FROM public.jl_entries;
```

Note: A3 is only runnable after `org_id` exists. Before that, use:
```sql
SELECT count(*) AS total_rows
FROM public.jl_entries;
```

## Phase B — conservative additive migration draft

This migration is intentionally additive. It preserves existing organisation resolution, leaves existing rows untouched, and does not change uniqueness or access policies until the preflight results have been reviewed.

```sql
BEGIN;

ALTER TABLE public.jl_entries
  ADD COLUMN IF NOT EXISTS org_id UUID
    REFERENCES public.jl_organisations(id),
  ADD COLUMN IF NOT EXISTS domain TEXT;

CREATE INDEX IF NOT EXISTS jl_entries_org_id_domain_idx
  ON public.jl_entries (org_id, domain);

-- Deliberately omitted:
-- * no replacement of jl_current_org_id()
-- * no blanket backfill of legacy rows
-- * no removal of UNIQUE(jl_id)
-- * no permissive RLS policy creation
-- * no membership RPC or role changes

COMMIT;
```

This migration alone does **not** complete tenant isolation. It creates the fields needed for a verified migration without making unsupported ownership or application-behaviour assumptions.

## Phase C — required checks before tenant policies are written

- Verify how the application writes `jl_entries`: whether `user_id`, `org_id`, `domain`, and `jl_id` are always supplied, and whether shared workspace entries can have a null `user_id`.
- Confirm that the active organisation is resolved from the authenticated user's server-side profile and that the user cannot change their organisation by editing client data.
- Identify all current policies and grants on each core table. RLS enabled without correct policies can block legitimate operations; broad policies can expose records.
- Audit duplicate `jl_id` values and all code paths that assume `jl_id` is globally unique before considering a composite key.
- Establish a least-privilege role matrix for owner/admin, supervisor, laboratory, hospital, clinical-trial and read-only users. The caller must not self-assign privileged roles.
- Define separate, least-privilege access for operational alerts and health logs; do not grant all authenticated users unrestricted access.
- Run tests with two distinct organisations and distinct accounts. Verify both allowed reads/writes and denied cross-organisation reads/writes.

## Acceptance criteria

Do not mark Priority 1 complete until all of the following are evidenced in staging:

- Organisation resolution works after login, refresh and re-login.
- A user cannot select or write another organisation's ID to bypass isolation.
- Cross-organisation reads, inserts, updates and deletes are denied.
- Existing legacy records remain intact and are not silently reassigned.
- Membership/role changes cannot elevate a normal user to admin or supervisor.
- Existing application save/load flows continue to work.
- Supabase security advisor findings are reviewed individually with evidence.

## Current execution status

- [x] Original bundle reviewed for high-risk assumptions.
- [x] Corrected, conservative migration approach drafted.
- [ ] Staging schema preflight captured.
- [ ] Final RLS policies derived from actual schema and role matrix.
- [ ] Staging migration applied and tested.
- [ ] Security advisor re-run and evidence recorded.

**Release gate:** no production migration, production deployment, or PR merge is authorised by this draft.


## Live schema baseline observed (read-only check, 2026-10-22)

This snapshot came from read-only catalog queries against the configured Supabase project. It is a baseline, **not** permission to modify production.

- `jl_entries` currently has: `id`, `jl_id`, nullable `user_id`, nullable text `organisation`, required `role`, `ts`, required JSONB `payload`, and `created_at`.
- `jl_entries` currently has a primary key on `id`, global `UNIQUE(jl_id)`, and a foreign key from `user_id` to `auth.users(id)`. The proposed `org_id` and `domain` columns are not present yet.
- Existing organisation-scoped policies on several core tables use `org_id = jl_current_org_id()`; therefore, replacing that resolver with JWT-claim logic would be a material behaviour change.
- The current catalog snapshot shows permissive policies on `alerts` and `system_health_log`, including public-role read/write or all-operation policies with `true` predicates. These are high-priority findings to investigate and remediate in a controlled environment.
- Several core-table policies are declared for the PostgreSQL `public` role rather than explicitly for `authenticated`. Because policy roles and grants interact, review effective grants and anon/authenticated behaviour together; do not assume the policy name alone makes it safe.
- No write query, migration, or production policy change was performed during this check.

## Next technical action

Capture effective table grants, RLS enabled/forced status, and the exact `jl_current_org_id()` definition. Then prepare a staging-only policy migration that removes anonymous access to alerts and health logs while preserving only the specific authenticated operational access the app requires. The final policy set must be tested with anon, organisation A, and organisation B sessions before any production release.
