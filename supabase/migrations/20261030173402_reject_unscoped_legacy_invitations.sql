-- Keep legacy unscoped invitations pending and fail closed; never activate a role
-- without an explicit workspace permission grant.
CREATE OR REPLACE FUNCTION public.jl_accept_organisation_invitation(p_org_id uuid,p_org_code text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_confirmed timestamptz; v_role text; v_count integer;
BEGIN
 IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT email_confirmed_at INTO v_confirmed FROM auth.users WHERE id=v_uid;
 IF v_confirmed IS NULL THEN RAISE EXCEPTION 'Verify your email before accepting an invitation' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.jl_organisations o WHERE o.id=p_org_id AND coalesce(o.active,true)
  AND upper(btrim(o.org_code))=upper(btrim(coalesce(p_org_code,'')))) THEN
  RAISE EXCEPTION 'Organisation code could not be verified' USING ERRCODE='42501';
 END IF;
 SELECT count(*),min(access_role) INTO v_count,v_role FROM public.jl_org_memberships
 WHERE organisation_id=p_org_id AND user_id=v_uid AND status='invited';
 IF v_count=0 THEN
  IF EXISTS(SELECT 1 FROM public.jl_org_memberships WHERE organisation_id=p_org_id AND user_id=v_uid AND status='active') THEN RETURN true; END IF;
  RAISE EXCEPTION 'No administrator-approved invitation exists for this account' USING ERRCODE='42501';
 END IF;
 IF v_count<>1 THEN RAISE EXCEPTION 'Multiple invitations exist; ask the administrator to resolve them' USING ERRCODE='42501'; END IF;
 IF v_role NOT IN ('hospital','laboratory','bioinformatics','clinical_trial','org_admin') THEN
  RAISE EXCEPTION 'This legacy invitation has no explicit workspace scope. Ask the administrator to issue a new workspace-scoped invitation.' USING ERRCODE='42501';
 END IF;
 IF v_role IN ('hospital','laboratory','bioinformatics')
 AND NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w WHERE w.org_id=p_org_id AND w.workspace_key=v_role AND w.status='active') THEN
  RAISE EXCEPTION 'Invited workspace is no longer enabled' USING ERRCODE='42501';
 END IF;
 IF v_role='clinical_trial'
 AND NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w WHERE w.org_id=p_org_id AND w.workspace_key='clinical_trials' AND w.status='active') THEN
  RAISE EXCEPTION 'Clinical Trials is not an active organisation entitlement' USING ERRCODE='42501';
 END IF;

 UPDATE public.jl_org_memberships SET status='active'
 WHERE organisation_id=p_org_id AND user_id=v_uid AND status='invited';
 GET DIAGNOSTICS v_count=ROW_COUNT;
 IF v_count<>1 THEN RAISE EXCEPTION 'Invitation could not be activated' USING ERRCODE='42501'; END IF;

 IF v_role IN ('hospital','laboratory','bioinformatics') THEN
  INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
  VALUES(p_org_id,v_uid,v_role,true,true,true,v_uid)
  ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
 ELSIF v_role='org_admin' THEN
  INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
  SELECT p_org_id,v_uid,w.workspace_key,true,true,true,v_uid FROM public.jl_organisation_workspaces w
  WHERE w.org_id=p_org_id AND w.status='active' AND w.workspace_key<>'clinical_trials'
  ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
 END IF;
 RETURN true;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) TO authenticated,service_role;
