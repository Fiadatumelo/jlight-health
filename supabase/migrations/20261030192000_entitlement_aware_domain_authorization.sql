-- Replace legacy singular-path authorization with explicit organisation entitlement checks.
-- Platform administrators do NOT receive implicit patient-data access through this helper.
-- Clinical Trials remains separately permissioned and tenant-isolated.

CREATE OR REPLACE FUNCTION public.jlight_has_domain_permission(
  p_organization_id uuid,
  p_domain text,
  p_access text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'auth'
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_org_active boolean;
BEGIN
  IF v_uid IS NULL
     OR p_organization_id IS NULL
     OR p_domain NOT IN ('hospital','laboratory','bioinformatics','clinical_trials')
     OR p_access NOT IN ('read','write','report') THEN
    RETURN false;
  END IF;

  SELECT coalesce(o.active, true)
    INTO v_org_active
  FROM public.jl_organisations o
  WHERE o.id = p_organization_id;

  IF v_org_active IS DISTINCT FROM true THEN
    RETURN false;
  END IF;

  -- Every workspace, including Clinical Trials, requires an explicit active
  -- organisation-level entitlement. A browser path, role claim, or admin flag
  -- cannot manufacture one.
  IF NOT EXISTS (
    SELECT 1
    FROM public.jl_organisation_workspaces w
    WHERE w.org_id = p_organization_id
      AND w.workspace_key = p_domain
      AND w.status = 'active'
  ) THEN
    RETURN false;
  END IF;

  IF p_domain = 'clinical_trials' THEN
    RETURN EXISTS (
      SELECT 1
      FROM public.jl_org_memberships m
      WHERE m.organisation_id = p_organization_id
        AND m.user_id = v_uid
        AND m.status = 'active'
        AND (
          (p_access = 'read' AND m.access_role IN
            ('owner','org_admin','clinical_trial','reviewer','read_only'))
          OR
          (p_access IN ('write','report') AND m.access_role IN
            ('owner','org_admin','clinical_trial'))
        )
    );
  END IF;

  RETURN EXISTS (
    SELECT 1
    FROM public.jlight_organization_memberships m
    JOIN public.jlight_membership_domain_permissions dp
      ON dp.organization_id = m.organization_id
     AND dp.auth_subject = m.auth_subject
     AND dp.domain = p_domain
    WHERE m.organization_id = p_organization_id
      AND m.auth_subject = v_uid
      AND m.active = true
      AND CASE p_access
        WHEN 'read' THEN dp.can_read
        WHEN 'write' THEN dp.can_read AND dp.can_write
        WHEN 'report' THEN dp.can_read AND dp.can_report
        ELSE false
      END
  );
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) FROM anon;
GRANT EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) TO authenticated, service_role;

COMMENT ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) IS
  'Authorizes only the caller''s active membership and explicit member permission inside an active organisation workspace entitlement. Platform-admin status alone never grants patient-data access; Clinical Trials uses its separate membership roles.';
