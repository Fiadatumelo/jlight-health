-- Keep the trigger-only synchronizer out of the PostgREST RPC surface.
REVOKE ALL ON FUNCTION public.jlight_sync_legacy_membership() FROM PUBLIC, anon, authenticated;

-- Reject null domain values explicitly rather than treating them as an implicit no-op.
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
  v_actor_role text;
  v_target_role text;
BEGIN
  IF v_actor IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  IF p_domain IS NULL OR p_domain NOT IN ('hospital','laboratory','bioinformatics') THEN
    RAISE EXCEPTION 'Clinical Trials access is managed separately and cannot be changed here'
      USING ERRCODE = '22023';
  END IF;
  IF coalesce(p_can_write, false) AND NOT coalesce(p_can_read, false) THEN
    RAISE EXCEPTION 'Write permission requires read permission' USING ERRCODE = '22023';
  END IF;
  IF coalesce(p_can_report, false) AND NOT coalesce(p_can_read, false) THEN
    RAISE EXCEPTION 'Report permission requires read permission' USING ERRCODE = '22023';
  END IF;

  SELECT m.role INTO v_actor_role
  FROM public.jlight_organization_memberships m
  WHERE m.organization_id = p_organization_id
    AND m.auth_subject = v_actor
    AND m.active = true;

  IF v_actor_role NOT IN ('owner','admin') OR v_actor_role IS NULL THEN
    RAISE EXCEPTION 'Only an active organisation owner or administrator can change domain access'
      USING ERRCODE = '42501';
  END IF;
  SELECT m.role INTO v_target_role
  FROM public.jlight_organization_memberships m
  WHERE m.organization_id = p_organization_id
    AND m.auth_subject = p_auth_subject
    AND m.active = true;
  IF v_target_role IS NULL THEN
    RAISE EXCEPTION 'The target user is not an active member of this organisation'
      USING ERRCODE = '42501';
  END IF;
  IF p_auth_subject = v_actor AND v_actor_role <> 'owner' THEN
    RAISE EXCEPTION 'Administrators cannot change their own domain permissions'
      USING ERRCODE = '42501';
  END IF;
  IF p_auth_subject = v_actor AND v_actor_role = 'owner'
     AND (NOT coalesce(p_can_read,false) OR NOT coalesce(p_can_write,false) OR NOT coalesce(p_can_report,false)) THEN
    RAISE EXCEPTION 'Owners cannot revoke their own domain access'
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

REVOKE ALL ON FUNCTION public.jlight_set_member_domain_permission(uuid, uuid, text, boolean, boolean, boolean) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_set_member_domain_permission(uuid, uuid, text, boolean, boolean, boolean) TO authenticated;
