-- Bridge legacy workspace memberships into the cross-section security model,
-- then expose a least-privilege owner/admin workflow for domain permissions.
BEGIN;

CREATE OR REPLACE FUNCTION public.jlight_sync_legacy_membership()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_org_role text;
  v_role text;
  v_active boolean := false;
BEGIN
  IF TG_OP = 'DELETE' THEN
    UPDATE public.jlight_organization_memberships
       SET active = false
     WHERE organization_id = OLD.organisation_id
       AND auth_subject = OLD.user_id;
    RETURN OLD;
  END IF;

  SELECT lower(coalesce(o.role, o.type, ''))
    INTO v_org_role
  FROM public.jl_organisations o
  WHERE o.id = NEW.organisation_id;

  IF NOT FOUND OR v_org_role IN ('trial', 'clinical_trial', 'clinical trial')
     OR NEW.access_role = 'clinical_trial' THEN
    UPDATE public.jlight_organization_memberships
       SET active = false
     WHERE organization_id = NEW.organisation_id
       AND auth_subject = NEW.user_id;
    RETURN NEW;
  END IF;

  v_role := CASE NEW.access_role
    WHEN 'owner' THEN 'owner'
    WHEN 'org_admin' THEN 'admin'
    WHEN 'hospital' THEN 'clinician'
    WHEN 'laboratory' THEN 'laboratory'
    WHEN 'bioinformatics' THEN 'bioinformatics'
    WHEN 'reviewer' THEN 'viewer'
    WHEN 'read_only' THEN 'viewer'
    ELSE NULL
  END;

  v_active := NEW.status = 'active' AND v_role IS NOT NULL;

  IF v_role IS NULL THEN
    UPDATE public.jlight_organization_memberships
       SET active = false
     WHERE organization_id = NEW.organisation_id
       AND auth_subject = NEW.user_id;
    RETURN NEW;
  END IF;

  INSERT INTO public.jlight_organization_memberships
    (organization_id, auth_subject, role, active, created_by)
  VALUES
    (NEW.organisation_id, NEW.user_id, v_role, v_active, coalesce(NEW.created_by, NEW.user_id))
  ON CONFLICT (auth_subject, organization_id) DO UPDATE
    SET role = CASE
          WHEN public.jlight_organization_memberships.role = 'owner'
               AND EXCLUDED.role <> 'owner'
            THEN 'owner'
          ELSE EXCLUDED.role
        END,
        active = EXCLUDED.active;

  -- The organisation owner receives the baseline permissions needed to administer
  -- the cross-section workspace. Other members receive no implicit domain access.
  IF NEW.access_role = 'owner' AND v_active THEN
    INSERT INTO public.jlight_membership_domain_permissions
      (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
    VALUES
      (NEW.organisation_id, NEW.user_id, 'hospital', true, true, true, NEW.user_id),
      (NEW.organisation_id, NEW.user_id, 'laboratory', true, true, true, NEW.user_id),
      (NEW.organisation_id, NEW.user_id, 'bioinformatics', true, true, true, NEW.user_id)
    ON CONFLICT (organization_id, auth_subject, domain) DO NOTHING;
  END IF;

  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS jlight_sync_legacy_membership_trigger ON public.jl_org_memberships;
CREATE TRIGGER jlight_sync_legacy_membership_trigger
AFTER INSERT OR UPDATE OF status, access_role, organisation_id, user_id OR DELETE
ON public.jl_org_memberships
FOR EACH ROW EXECUTE FUNCTION public.jlight_sync_legacy_membership();

-- Backfill current non-trial memberships using the same role mapping. Existing
-- permission grants are preserved; no broad access is assigned to ordinary members.
INSERT INTO public.jlight_organization_memberships
  (organization_id, auth_subject, role, active, created_by)
SELECT DISTINCT ON (m.organisation_id, m.user_id)
  m.organisation_id,
  m.user_id,
  CASE m.access_role
    WHEN 'owner' THEN 'owner'
    WHEN 'org_admin' THEN 'admin'
    WHEN 'hospital' THEN 'clinician'
    WHEN 'laboratory' THEN 'laboratory'
    WHEN 'bioinformatics' THEN 'bioinformatics'
    WHEN 'reviewer' THEN 'viewer'
    WHEN 'read_only' THEN 'viewer'
  END,
  (m.status = 'active'),
  coalesce(m.created_by, m.user_id)
FROM public.jl_org_memberships m
JOIN public.jl_organisations o ON o.id = m.organisation_id
WHERE m.access_role IN ('owner','org_admin','hospital','laboratory','bioinformatics','reviewer','read_only')
  AND m.access_role <> 'clinical_trial'
  AND lower(coalesce(o.role, o.type, '')) NOT IN ('trial','clinical_trial','clinical trial')
ORDER BY m.organisation_id, m.user_id,
  CASE m.access_role
    WHEN 'owner' THEN 1
    WHEN 'org_admin' THEN 2
    WHEN 'hospital' THEN 3
    WHEN 'laboratory' THEN 4
    WHEN 'bioinformatics' THEN 5
    WHEN 'reviewer' THEN 6
    WHEN 'read_only' THEN 7
    ELSE 99
  END
ON CONFLICT (auth_subject, organization_id) DO UPDATE
  SET role = CASE
        WHEN public.jlight_organization_memberships.role = 'owner'
             AND EXCLUDED.role <> 'owner'
          THEN 'owner'
        ELSE EXCLUDED.role
      END,
      active = EXCLUDED.active;

-- Preserve least privilege: only the owner receives baseline cross-section access.
INSERT INTO public.jlight_membership_domain_permissions
  (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
SELECT m.organization_id, m.auth_subject, d.domain, true, true, true, m.auth_subject
FROM public.jlight_organization_memberships m
JOIN public.jl_organisations o ON o.id = m.organization_id
CROSS JOIN (VALUES ('hospital'), ('laboratory'), ('bioinformatics')) AS d(domain)
WHERE m.role = 'owner'
  AND m.active = true
  AND lower(coalesce(o.role, o.type, '')) NOT IN ('trial','clinical_trial','clinical trial')
ON CONFLICT (organization_id, auth_subject, domain) DO NOTHING;

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
         coalesce(u.email, ''),
         coalesce(nullif(btrim(p.full_name), ''), split_part(coalesce(u.email, 'Member'), '@', 1)),
         m.role,
         m.active,
         d.domain,
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

CREATE OR REPLACE FUNCTION public.jlight_set_member_domain_permission(
  p_organization_id uuid,
  p_auth_subject uuid,
  p_domain text,
  p_can_read boolean,
  p_can_write boolean,
  p_can_report boolean
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
DECLARE
  v_actor uuid := auth.uid();
  v_role text;
BEGIN
  IF v_actor IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  IF p_domain NOT IN ('hospital','laboratory','bioinformatics') THEN
    RAISE EXCEPTION 'Clinical Trials access is managed separately and cannot be changed here'
      USING ERRCODE = '22023';
  END IF;
  IF coalesce(p_can_write, false) AND NOT coalesce(p_can_read, false) THEN
    RAISE EXCEPTION 'Write permission requires read permission' USING ERRCODE = '22023';
  END IF;
  IF coalesce(p_can_report, false) AND NOT coalesce(p_can_read, false) THEN
    RAISE EXCEPTION 'Report permission requires read permission' USING ERRCODE = '22023';
  END IF;

  SELECT m.role INTO v_role
  FROM public.jlight_organization_memberships m
  WHERE m.organization_id = p_organization_id
    AND m.auth_subject = v_actor
    AND m.active = true;

  IF v_role NOT IN ('owner','admin') OR v_role IS NULL THEN
    RAISE EXCEPTION 'Only an active organisation owner or administrator can change domain access'
      USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.jlight_organization_memberships m
    WHERE m.organization_id = p_organization_id
      AND m.auth_subject = p_auth_subject
      AND m.active = true
  ) THEN
    RAISE EXCEPTION 'The target user is not an active member of this organisation'
      USING ERRCODE = '42501';
  END IF;
  IF p_auth_subject = v_actor AND v_role <> 'owner' THEN
    RAISE EXCEPTION 'Administrators cannot change their own domain permissions'
      USING ERRCODE = '42501';
  END IF;

  IF NOT coalesce(p_can_read, false)
     AND NOT coalesce(p_can_write, false)
     AND NOT coalesce(p_can_report, false) THEN
    DELETE FROM public.jlight_membership_domain_permissions
    WHERE organization_id = p_organization_id
      AND auth_subject = p_auth_subject
      AND domain = p_domain;
  ELSE
    INSERT INTO public.jlight_membership_domain_permissions
      (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
    VALUES
      (p_organization_id, p_auth_subject, p_domain,
       coalesce(p_can_read, false), coalesce(p_can_write, false),
       coalesce(p_can_report, false), v_actor)
    ON CONFLICT (organization_id, auth_subject, domain) DO UPDATE
      SET can_read = EXCLUDED.can_read,
          can_write = EXCLUDED.can_write,
          can_report = EXCLUDED.can_report,
          granted_by = EXCLUDED.granted_by,
          created_at = now();
  END IF;

  RETURN jsonb_build_object(
    'success', true,
    'organization_id', p_organization_id,
    'auth_subject', p_auth_subject,
    'domain', p_domain,
    'can_read', coalesce(p_can_read, false),
    'can_write', coalesce(p_can_write, false),
    'can_report', coalesce(p_can_report, false)
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.jlight_list_org_domain_access(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_list_org_domain_access(uuid) TO authenticated;
REVOKE ALL ON FUNCTION public.jlight_set_member_domain_permission(uuid, uuid, text, boolean, boolean, boolean) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_set_member_domain_permission(uuid, uuid, text, boolean, boolean, boolean) TO authenticated;

COMMIT;
