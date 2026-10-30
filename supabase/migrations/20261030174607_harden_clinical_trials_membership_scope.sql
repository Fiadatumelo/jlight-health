-- Clinical Trials member roles are separate from standard workspace roles.
-- Legacy reviewer/read_only access is retained only for legacy CT-only organisations;
-- it never leaks into a multi-path organisation as an implicit CT grant.
CREATE OR REPLACE FUNCTION public.jlight_has_domain_permission(
 p_organization_id uuid,p_domain text,p_access text
)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_org_active boolean;
BEGIN
 IF v_uid IS NULL OR p_organization_id IS NULL
 OR p_domain NOT IN ('hospital','laboratory','bioinformatics','clinical_trials')
 OR p_access NOT IN ('read','write','report') THEN RETURN false; END IF;
 SELECT coalesce(o.active,true) INTO v_org_active FROM public.jl_organisations o WHERE o.id=p_organization_id;
 IF v_org_active IS DISTINCT FROM true THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w
  WHERE w.org_id=p_organization_id AND w.workspace_key=p_domain AND w.status='active') THEN RETURN false; END IF;

 IF p_domain='clinical_trials' THEN
  RETURN EXISTS(
   SELECT 1 FROM public.jl_org_memberships m
   JOIN public.jl_organisations o ON o.id=m.organisation_id
   WHERE m.organisation_id=p_organization_id AND m.user_id=v_uid AND m.status='active'
    AND (
      m.access_role IN ('owner','org_admin','clinical_trial')
      OR (
        m.access_role IN ('reviewer','read_only')
        AND lower(coalesce(nullif(o.type,'multi'),o.role)) IN ('clinical_trials','trial','clinical_trial')
      )
    )
    AND (
      p_access='read'
      OR (p_access IN ('write','report') AND m.access_role IN ('owner','org_admin','clinical_trial'))
    )
  );
 END IF;

 RETURN EXISTS(
  SELECT 1 FROM public.jlight_organization_memberships m
  JOIN public.jlight_membership_domain_permissions dp
   ON dp.organization_id=m.organization_id AND dp.auth_subject=m.auth_subject AND dp.domain=p_domain
  WHERE m.organization_id=p_organization_id AND m.auth_subject=v_uid AND m.active=true
   AND CASE p_access WHEN 'read' THEN dp.can_read
    WHEN 'write' THEN dp.can_read AND dp.can_write
    WHEN 'report' THEN dp.can_read AND dp.can_report ELSE false END
 );
END;
$function$;
REVOKE ALL ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) TO authenticated,service_role;

CREATE OR REPLACE FUNCTION public.jl_list_my_workspaces(p_org_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_result jsonb;
BEGIN
 IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 WITH member_orgs AS (
  SELECT DISTINCT o.id,o.name,o.org_code,o.type,o.role
  FROM public.jl_organisations o
  WHERE coalesce(o.active,true)=true
    AND (p_org_id IS NULL OR o.id=p_org_id)
    AND (
      EXISTS(SELECT 1 FROM public.jlight_organization_memberships m
       WHERE m.organization_id=o.id AND m.auth_subject=v_uid AND m.active=true)
      OR EXISTS(SELECT 1 FROM public.jl_org_memberships m
       WHERE m.organisation_id=o.id AND m.user_id=v_uid AND m.status='active')
    )
 )
 SELECT COALESCE(
  jsonb_agg(
   jsonb_build_object(
    'organisation_id',o.id,
    'organisation_name',o.name,
    'organisation_code',o.org_code,
    'workspaces',(
     SELECT COALESCE(
      jsonb_agg(
       jsonb_build_object(
        'key',w.workspace_key,
        'label',CASE w.workspace_key
         WHEN 'hospital' THEN 'Hospital'
         WHEN 'laboratory' THEN 'Laboratory'
         WHEN 'bioinformatics' THEN 'Bioinformatics'
         ELSE 'Clinical Trials' END
       ) ORDER BY w.workspace_key
      ),'[]'::jsonb
     )
     FROM public.jl_organisation_workspaces w
     WHERE w.org_id=o.id AND w.status='active'
      AND (
       (w.workspace_key='clinical_trials' AND EXISTS(
        SELECT 1 FROM public.jl_org_memberships tm
        WHERE tm.organisation_id=o.id AND tm.user_id=v_uid AND tm.status='active'
         AND (
          tm.access_role IN ('owner','org_admin','clinical_trial')
          OR (tm.access_role IN ('reviewer','read_only')
           AND lower(coalesce(nullif(o.type,'multi'),o.role)) IN ('clinical_trials','trial','clinical_trial'))
         )
       ))
       OR
       (w.workspace_key<>'clinical_trials' AND EXISTS(
        SELECT 1 FROM public.jlight_organization_memberships mm
        JOIN public.jlight_membership_domain_permissions dp
         ON dp.organization_id=mm.organization_id AND dp.auth_subject=mm.auth_subject
        WHERE mm.organization_id=o.id AND mm.auth_subject=v_uid AND mm.active=true
         AND dp.domain=w.workspace_key AND dp.can_read=true
       ))
      )
    )
   ) ORDER BY o.name
  ),'[]'::jsonb
 ) INTO v_result
 FROM member_orgs o;
 RETURN v_result;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_list_my_workspaces(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_list_my_workspaces(uuid) TO authenticated,service_role;

CREATE OR REPLACE FUNCTION public.jl_link_user_to_organisation(
 p_org_id uuid,p_org_code text,p_full_name text DEFAULT NULL,p_workspace_role text DEFAULT 'operator'
)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_org public.jl_organisations%rowtype; v_can_access boolean; v_role text; v_name text;
BEGIN
 IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT * INTO v_org FROM public.jl_organisations o
 WHERE o.id=p_org_id AND coalesce(o.active,true)=true AND upper(btrim(o.org_code))=upper(btrim(coalesce(p_org_code,'')));
 IF NOT FOUND THEN RAISE EXCEPTION 'Organisation code could not be verified' USING ERRCODE='42501'; END IF;

 SELECT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w WHERE w.org_id=v_org.id AND w.status='active'
  AND (
   (w.workspace_key='clinical_trials' AND EXISTS(
    SELECT 1 FROM public.jl_org_memberships tm WHERE tm.organisation_id=v_org.id AND tm.user_id=v_uid AND tm.status='active'
     AND (tm.access_role IN ('owner','org_admin','clinical_trial')
      OR (tm.access_role IN ('reviewer','read_only')
       AND lower(coalesce(nullif(v_org.type,'multi'),v_org.role)) IN ('clinical_trials','trial','clinical_trial')))
   ))
   OR (w.workspace_key<>'clinical_trials' AND EXISTS(
    SELECT 1 FROM public.jlight_organization_memberships mm
    JOIN public.jlight_membership_domain_permissions dp ON dp.organization_id=mm.organization_id AND dp.auth_subject=mm.auth_subject
    WHERE mm.organization_id=v_org.id AND mm.auth_subject=v_uid AND mm.active=true AND dp.domain=w.workspace_key AND dp.can_read=true
   ))
  )) INTO v_can_access;
 IF NOT v_can_access THEN RAISE EXCEPTION 'An active administrator-approved membership and workspace permission are required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.jl_user_profiles p WHERE p.user_id=v_uid AND coalesce(p.active,true)=false) THEN
  RAISE EXCEPTION 'This account is inactive. Contact the organisation administrator.' USING ERRCODE='42501';
 END IF;
 SELECT CASE
  WHEN EXISTS(SELECT 1 FROM public.jl_org_memberships m WHERE m.organisation_id=v_org.id AND m.user_id=v_uid AND m.status='active' AND m.access_role IN ('owner','org_admin'))
   OR EXISTS(SELECT 1 FROM public.jlight_organization_memberships m WHERE m.organization_id=v_org.id AND m.auth_subject=v_uid AND m.active=true AND m.role IN ('owner','admin')) THEN 'admin'
  WHEN EXISTS(SELECT 1 FROM public.jl_org_memberships m WHERE m.organisation_id=v_org.id AND m.user_id=v_uid AND m.status='active' AND m.access_role IN ('reviewer','read_only')) THEN 'viewer'
  ELSE 'operator' END INTO v_role;
 v_name:=coalesce(nullif(btrim(p_full_name),''),split_part(coalesce(auth.jwt()->>'email','JLIGHT User'),'@',1));
 INSERT INTO public.jl_user_profiles(user_id,org_id,full_name,workspace_role,active,last_seen)
 VALUES(v_uid,v_org.id,v_name,v_role,true,now())
 ON CONFLICT(user_id) DO UPDATE SET org_id=EXCLUDED.org_id,
  full_name=CASE WHEN nullif(btrim(p_full_name),'') IS NOT NULL THEN EXCLUDED.full_name ELSE public.jl_user_profiles.full_name END,
  workspace_role=EXCLUDED.workspace_role,active=true,last_seen=now();
 RETURN v_org.id;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_link_user_to_organisation(uuid,text,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid,text,text,text) TO authenticated,service_role;

CREATE OR REPLACE FUNCTION public.jl_list_trial_members(p_org_id uuid)
RETURNS TABLE(auth_subject uuid,email text,display_name text,membership_role text,membership_active boolean,domain text,can_read boolean,can_write boolean,can_report boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_actor uuid:=auth.uid();
BEGIN
 IF v_actor IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(
  SELECT 1 FROM public.jl_organisations o
  JOIN public.jl_organisation_workspaces w ON w.org_id=o.id AND w.workspace_key='clinical_trials' AND w.status='active'
  JOIN public.jl_org_memberships m ON m.organisation_id=o.id
  WHERE o.id=p_org_id AND coalesce(o.active,true)=true
   AND m.user_id=v_actor AND m.status='active' AND m.access_role IN ('owner','org_admin')
 ) THEN RAISE EXCEPTION 'Only an active Clinical Trials owner or administrator can list members' USING ERRCODE='42501'; END IF;
 RETURN QUERY
 SELECT m.user_id,coalesce(u.email,'')::text,
  coalesce(nullif(btrim(p.full_name),''),split_part(coalesce(u.email,'Member'),'@',1))::text,
  m.access_role::text,(m.status='active'),'clinical_trials'::text,
  (m.status='active' AND (
    m.access_role IN ('owner','org_admin','clinical_trial')
    OR (m.access_role IN ('reviewer','read_only') AND lower(coalesce(nullif(o.type,'multi'),o.role)) IN ('clinical_trials','trial','clinical_trial'))
  )),
  (m.status='active' AND m.access_role IN ('owner','org_admin','clinical_trial')),
  (m.status='active' AND m.access_role IN ('owner','org_admin','clinical_trial'))
 FROM public.jl_org_memberships m
 JOIN public.jl_organisations o ON o.id=m.organisation_id
 LEFT JOIN auth.users u ON u.id=m.user_id
 LEFT JOIN public.jl_user_profiles p ON p.user_id=m.user_id
 WHERE m.organisation_id=p_org_id
  AND (m.access_role IN ('owner','org_admin','clinical_trial')
   OR (m.access_role IN ('reviewer','read_only') AND lower(coalesce(nullif(o.type,'multi'),o.role)) IN ('clinical_trials','trial','clinical_trial')))
 ORDER BY (m.access_role='owner') DESC,(m.access_role='org_admin') DESC,display_name;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_list_trial_members(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_list_trial_members(uuid) TO authenticated,service_role;

CREATE OR REPLACE FUNCTION public.jl_resolve_lab_org(p_org_code text)
RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','auth'
AS $function$
DECLARE v_count integer; v_id uuid;
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING errcode='28000'; END IF;
 IF nullif(btrim(p_org_code),'') IS NULL THEN RAISE EXCEPTION 'Laboratory organisation code is required' USING errcode='22023'; END IF;
 SELECT count(*),min(o.id::text)::uuid INTO v_count,v_id
 FROM public.jl_organisations o
 WHERE upper(btrim(o.org_code))=upper(btrim(p_org_code)) AND o.role='Laboratory' AND coalesce(o.active,true)=true
  AND EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w
   WHERE w.org_id=o.id AND w.workspace_key='laboratory' AND w.status='active');
 IF v_count<>1 THEN RAISE EXCEPTION 'Laboratory code is invalid or ambiguous' USING errcode='22023'; END IF;
 RETURN v_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_resolve_lab_org(text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_resolve_lab_org(text) TO authenticated,service_role;
