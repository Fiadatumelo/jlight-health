-- Invitations are scoped to a specific entitled workspace. Generic reviewer/read-only
-- roles are disabled until a dedicated per-workspace invitation scope is available.
CREATE OR REPLACE FUNCTION public.jl_invite_org_member(p_email text,p_access_role text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_actor uuid:=auth.uid(); v_org_id uuid; v_role text; v_target uuid; v_status text;
BEGIN
 IF v_actor IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 IF nullif(btrim(p_email),'') IS NULL OR position('@' in p_email)<2 OR length(p_email)>320 THEN
  RAISE EXCEPTION 'Enter a valid email address' USING ERRCODE='22023';
 END IF;
 SELECT p.org_id INTO v_org_id
 FROM public.jl_user_profiles p JOIN public.jl_organisations o ON o.id=p.org_id
 WHERE p.user_id=v_actor AND coalesce(p.active,true) AND coalesce(o.active,true)
  AND (EXISTS(SELECT 1 FROM public.jlight_organization_memberships m WHERE m.organization_id=o.id AND m.auth_subject=v_actor AND m.active=true AND m.role IN ('owner','admin'))
   OR EXISTS(SELECT 1 FROM public.jl_org_memberships m WHERE m.organisation_id=o.id AND m.user_id=v_actor AND m.status='active' AND m.access_role IN ('owner','org_admin')))
 LIMIT 1;
 IF v_org_id IS NULL THEN RAISE EXCEPTION 'Active organisation owner or administrator required' USING ERRCODE='42501'; END IF;

 v_role:=coalesce(nullif(btrim(p_access_role),''),'read_only');
 IF v_role NOT IN ('hospital','laboratory','bioinformatics','clinical_trial','org_admin') THEN
  RAISE EXCEPTION 'Choose a specific entitled workspace role or organisation administrator. Generic reviewer/read-only invitations are disabled until scoped invitations are supported.' USING ERRCODE='22023';
 END IF;
 IF v_role<>'org_admin' THEN
  IF NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w
    WHERE w.org_id=v_org_id AND w.workspace_key=CASE v_role WHEN 'clinical_trial' THEN 'clinical_trials' ELSE v_role END AND w.status='active') THEN
   RAISE EXCEPTION 'The organisation does not have this approved workspace' USING ERRCODE='42501';
  END IF;
 END IF;
 SELECT u.id INTO v_target FROM auth.users u WHERE lower(u.email)=lower(btrim(p_email)) LIMIT 1;
 IF v_target IS NULL THEN RAISE EXCEPTION 'The user must first create and verify a JLIGHT email-code account' USING ERRCODE='22023'; END IF;
 IF v_target=v_actor THEN RAISE EXCEPTION 'You cannot invite yourself' USING ERRCODE='22023'; END IF;
 SELECT status INTO v_status FROM public.jl_org_memberships
 WHERE organisation_id=v_org_id AND user_id=v_target AND access_role=v_role LIMIT 1;
 IF v_status='active' THEN RAISE EXCEPTION 'This user is already an active member' USING ERRCODE='23505'; END IF;
 INSERT INTO public.jl_org_memberships(organisation_id,user_id,access_role,status,created_by)
 VALUES(v_org_id,v_target,v_role,'invited',v_actor)
 ON CONFLICT(organisation_id,user_id,access_role) DO UPDATE SET status='invited',created_by=v_actor;
 RETURN jsonb_build_object('success',true,'organisation_id',v_org_id,'email',lower(btrim(p_email)),
  'access_role',v_role,'status','invited');
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_accept_organisation_invitation(p_org_id uuid,p_org_code text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
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
 UPDATE public.jl_org_memberships SET status='active'
 WHERE organisation_id=p_org_id AND user_id=v_uid AND status='invited';
 GET DIAGNOSTICS v_count=ROW_COUNT;
 IF v_count<>1 THEN RAISE EXCEPTION 'Invitation could not be activated' USING ERRCODE='42501'; END IF;

 IF v_role IN ('hospital','laboratory','bioinformatics') THEN
  IF NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w WHERE w.org_id=p_org_id AND w.workspace_key=v_role AND w.status='active') THEN
   RAISE EXCEPTION 'Invited workspace is no longer enabled' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
  VALUES(p_org_id,v_uid,v_role,true,true,true,v_uid)
  ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
 ELSIF v_role='org_admin' THEN
  -- An organisation administrator receives access only to currently active entitlements.
  INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
  SELECT p_org_id,v_uid,w.workspace_key,true,true,true,v_uid
  FROM public.jl_organisation_workspaces w
  WHERE w.org_id=p_org_id AND w.status='active' AND w.workspace_key<>'clinical_trials'
  ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
 ELSIF v_role='clinical_trial' THEN
  IF NOT EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w WHERE w.org_id=p_org_id AND w.workspace_key='clinical_trials' AND w.status='active') THEN
   RAISE EXCEPTION 'Clinical Trials is not an active organisation entitlement' USING ERRCODE='42501';
  END IF;
 END IF;
 RETURN true;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_invite_org_member(text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_invite_org_member(text,text) TO authenticated,service_role;
REVOKE ALL ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) TO authenticated,service_role;
