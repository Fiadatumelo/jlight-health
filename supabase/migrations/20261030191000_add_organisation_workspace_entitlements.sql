-- Additive multi-workspace entitlement foundation. No existing access is widened.
-- Direct client table access is intentionally denied; authenticated workflows
-- will be mediated by reviewed RPCs in a subsequent application migration.

CREATE TABLE IF NOT EXISTS public.jl_organisation_workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
  workspace_key text NOT NULL CHECK (workspace_key IN ('hospital','laboratory','bioinformatics','clinical_trials')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
  provisioning_source text NOT NULL CHECK (provisioning_source IN ('initial_registration','admin_approval','legacy_backfill')),
  approved_by uuid NULL REFERENCES auth.users(id) ON DELETE SET NULL,
  approved_at timestamptz NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT jl_organisation_workspaces_org_workspace_uniq UNIQUE (org_id, workspace_key),
  CONSTRAINT jl_organisation_workspaces_approval_consistency CHECK (
    (provisioning_source = 'admin_approval' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
    OR provisioning_source <> 'admin_approval'
  )
);

CREATE TABLE IF NOT EXISTS public.jl_workspace_access_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
  requested_workspace text NOT NULL CHECK (requested_workspace IN ('hospital','laboratory','bioinformatics','clinical_trials')),
  status text NOT NULL DEFAULT 'pending_review'
    CHECK (status IN ('pending_review','approved','rejected','withdrawn')),
  evidence_reference text NULL,
  criteria_version text NULL,
  eligibility_result jsonb NULL,
  submitted_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  reviewed_by uuid NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  reviewed_at timestamptz NULL,
  decision_reason text NULL,
  CONSTRAINT jl_workspace_access_requests_review_consistency CHECK (
    (status IN ('pending_review','withdrawn') AND reviewed_by IS NULL AND reviewed_at IS NULL)
    OR (status IN ('approved','rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS jl_workspace_access_requests_one_pending
  ON public.jl_workspace_access_requests(org_id, requested_workspace)
  WHERE status = 'pending_review';

CREATE INDEX IF NOT EXISTS jl_workspace_access_requests_org_status_idx
  ON public.jl_workspace_access_requests(org_id, status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS jl_organisation_workspaces_active_idx
  ON public.jl_organisation_workspaces(org_id, workspace_key)
  WHERE status = 'active';

ALTER TABLE public.jl_organisation_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jl_organisation_workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE public.jl_workspace_access_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jl_workspace_access_requests FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.jl_organisation_workspaces FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.jl_workspace_access_requests FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.jl_organisation_workspaces TO service_role;
GRANT ALL ON TABLE public.jl_workspace_access_requests TO service_role;

-- Conservative compatibility backfill: only known, unambiguous legacy paths.
INSERT INTO public.jl_organisation_workspaces
  (org_id, workspace_key, status, provisioning_source, approved_at)
SELECT o.id,
       lower(coalesce(nullif(o.type, 'multi'), o.role)),
       'active',
       'legacy_backfill',
       now()
FROM public.jl_organisations o
WHERE lower(coalesce(nullif(o.type, 'multi'), o.role))
      IN ('hospital','laboratory','bioinformatics','clinical_trials')
ON CONFLICT (org_id, workspace_key) DO NOTHING;

COMMENT ON TABLE public.jl_organisation_workspaces IS
  'Authoritative organisation-level workspace entitlements. Client roles have no direct table grants; access is mediated by reviewed, authenticated RPCs.';
COMMENT ON TABLE public.jl_workspace_access_requests IS
  'Organisation requests for additional workspace entitlements. Pending requests grant no access; only JLIGHT Platform Administration may approve.';
