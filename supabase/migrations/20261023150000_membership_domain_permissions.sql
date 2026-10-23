-- Explicit per-membership domain permissions. Fail closed until an administrator grants access.
CREATE TABLE IF NOT EXISTS public.jlight_membership_domain_permissions (
    organization_id uuid NOT NULL,
    auth_subject uuid NOT NULL,
    domain text NOT NULL CHECK (domain IN ('hospital','laboratory','bioinformatics','clinical_trials')),
    can_read boolean NOT NULL DEFAULT false,
    can_write boolean NOT NULL DEFAULT false,
    can_report boolean NOT NULL DEFAULT false,
    granted_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, auth_subject, domain),
    FOREIGN KEY (organization_id, auth_subject)
      REFERENCES public.jlight_organization_memberships (organization_id, auth_subject)
      ON DELETE CASCADE,
    CHECK (NOT can_write OR can_read),
    CHECK (NOT can_report OR can_read)
);
ALTER TABLE public.jlight_membership_domain_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jlight_membership_domain_permissions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.jlight_membership_domain_permissions FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.jlight_membership_domain_permissions TO jlight_runtime;
DROP POLICY IF EXISTS jlight_domain_permissions_self_read ON public.jlight_membership_domain_permissions;
CREATE POLICY jlight_domain_permissions_self_read
ON public.jlight_membership_domain_permissions
FOR SELECT TO jlight_runtime
USING (
  organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid
  AND auth_subject = NULLIF(current_setting('jlight.auth_subject', true), '')::uuid
);
