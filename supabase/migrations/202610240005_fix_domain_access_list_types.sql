-- Align auth/profile varchar fields with the explicit text return contract.
CREATE OR REPLACE FUNCTION public.jlight_list_org_domain_access(p_organization_id uuid)
RETURNS TABLE (
  auth_subject uuid,
  email text,
  display_name text,
  membership_role text,
  membership_active boolean,
  domain text,
  can_read boolean,
  can_write boolean,
  can_report boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
DECLARE
  v_actor uuid := auth.uid();
BEGIN
  IF v_actor IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.jlight_organization_memberships m
    WHERE m.organization_id = p_organization_id
      AND m.auth_subject = v_actor
      AND m.active = true
      AND m.role IN ('owner','admin')
  ) THEN
    RAISE EXCEPTION 'Only an active organisation owner or administrator can manage domain access'
      USING ERRCODE = '42501';
  END IF;

  RETURN QUERY
  SELECT m.auth_subject,
         coalesce(u.email, '')::text,
         coalesce(nullif(btrim(p.full_name), ''), split_part(coalesce(u.email, 'Member'), '@', 1))::text,
         m.role::text,
         m.active,
         d.domain::text,
         coalesce(dp.can_read, false),
         coalesce(dp.can_write, false),
         coalesce(dp.can_report, false)
  FROM public.jlight_organization_memberships m
  LEFT JOIN auth.users u ON u.id = m.auth_subject
  LEFT JOIN public.jl_user_profiles p ON p.user_id = m.auth_subject
  CROSS JOIN (VALUES ('hospital'), ('laboratory'), ('bioinformatics')) AS d(domain)
  LEFT JOIN public.jlight_membership_domain_permissions dp
    ON dp.organization_id = m.organization_id
   AND dp.auth_subject = m.auth_subject
   AND dp.domain = d.domain
  WHERE m.organization_id = p_organization_id
  ORDER BY (m.role = 'owner') DESC, (m.role = 'admin') DESC, display_name, d.domain;
END;
$function$;

REVOKE ALL ON FUNCTION public.jlight_list_org_domain_access(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_list_org_domain_access(uuid) TO authenticated;
