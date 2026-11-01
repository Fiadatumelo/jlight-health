-- Permit multi-path organisation classification only from the trusted atomic registration RPC.
CREATE OR REPLACE FUNCTION public.jl_guard_trial_org_role()
RETURNS trigger LANGUAGE plpgsql SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_type text;
BEGIN
 IF TG_OP='INSERT' AND current_user NOT IN ('postgres','service_role','supabase_admin') THEN
  RAISE EXCEPTION 'Organisations must be created through the approved JLIGHT provisioning workflow' USING ERRCODE='42501';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.role IS DISTINCT FROM OLD.role OR NEW.type IS DISTINCT FROM OLD.type)
 AND current_user NOT IN ('postgres','service_role','supabase_admin') THEN
  RAISE EXCEPTION 'Organisation classification is system-managed and cannot be changed by workspace members' USING ERRCODE='42501';
 END IF;
 v_type:=lower(coalesce(NEW.type,''));
 IF v_type='multi' THEN
  IF lower(coalesce(NEW.role,''))<>'multi' OR current_user NOT IN ('postgres','service_role','supabase_admin')
   OR coalesce(current_setting('jlight.multi_workspace_registration',true),'')<>'approved' THEN
   RAISE EXCEPTION 'Multi-path organisations must be created by the approved multi-workspace registration workflow' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
 END IF;
 IF v_type NOT IN ('hospital','laboratory','bioinformatics','clinical_trials') THEN
  RAISE EXCEPTION 'Unsupported JLIGHT organisation path' USING ERRCODE='22023';
 END IF;
 IF (lower(NEW.role)='hospital' AND v_type<>'hospital')
 OR (lower(NEW.role)='laboratory' AND v_type NOT IN ('laboratory','bioinformatics'))
 OR (lower(NEW.role)='trial' AND v_type<>'clinical_trials') THEN
  RAISE EXCEPTION 'Organisation role and system-assigned path do not match' USING ERRCODE='22023';
 END IF;
 IF lower(NEW.role)='trial' AND current_user NOT IN ('postgres','service_role','supabase_admin')
 AND (TG_OP='INSERT' OR OLD.role IS DISTINCT FROM NEW.role) THEN
  RAISE EXCEPTION 'Clinical-trial organisations require approved provisioning' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_register_organisation_multi(p_name text,p_workspace_keys text[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth','extensions'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_email text; v_name text:=nullif(btrim(p_name),'');
 v_keys text[]; v_code text; v_org public.jl_organisations%rowtype; v_attempt integer:=0; v_workspace text;
BEGIN
 IF v_uid IS NULL THEN RAISE EXCEPTION 'Verified email-code sign-in is required' USING ERRCODE='42501'; END IF;
 SELECT lower(email) INTO v_email FROM auth.users WHERE id=v_uid AND email_confirmed_at IS NOT NULL;
 IF v_email IS NULL THEN RAISE EXCEPTION 'Verify your email before registering an organisation' USING ERRCODE='42501'; END IF;
 IF v_name IS NULL OR length(v_name)<2 OR length(v_name)>180 THEN RAISE EXCEPTION 'Organisation name must contain 2 to 180 characters' USING ERRCODE='22023'; END IF;
 IF p_workspace_keys IS NULL OR cardinality(p_workspace_keys)<1 OR cardinality(p_workspace_keys)>4 THEN RAISE EXCEPTION 'Select between one and four JLIGHT pathways' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM unnest(p_workspace_keys) x WHERE x IS NULL OR x NOT IN ('hospital','laboratory','bioinformatics','clinical_trials')) THEN RAISE EXCEPTION 'One or more selected JLIGHT pathways are invalid' USING ERRCODE='22023'; END IF;
 SELECT array_agg(DISTINCT x ORDER BY x) INTO v_keys FROM unnest(p_workspace_keys) x;
 IF cardinality(v_keys)<>cardinality(p_workspace_keys) THEN RAISE EXCEPTION 'Duplicate pathway selections are not allowed' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM public.jl_user_profiles p WHERE p.user_id=v_uid AND coalesce(p.active,true))
 OR EXISTS(SELECT 1 FROM public.jl_organisations o WHERE o.owner_user_id=v_uid AND coalesce(o.active,true)) THEN
  RAISE EXCEPTION 'This account is already linked to an active organisation. Sign in to that organisation instead.' USING ERRCODE='23505';
 END IF;
 LOOP
  v_attempt:=v_attempt+1; v_code:='JLI-'||upper(encode(extensions.gen_random_bytes(8),'hex'));
  EXIT WHEN NOT EXISTS(SELECT 1 FROM public.jl_organisations o WHERE upper(o.org_code)=v_code);
  IF v_attempt>=10 THEN RAISE EXCEPTION 'Could not generate a unique organisation code. Retry registration.'; END IF;
 END LOOP;
 PERFORM set_config('jlight.multi_workspace_registration','approved',true);
 INSERT INTO public.jl_organisations(name,role,type,owner_email,owner_user_id,org_code,active,created_at,updated_at)
 VALUES(v_name,'multi','multi',v_email,v_uid,v_code,true,now(),now()) RETURNING * INTO v_org;
 PERFORM set_config('jlight.multi_workspace_registration','',true);
 FOREACH v_workspace IN ARRAY v_keys LOOP
  INSERT INTO public.jl_organisation_workspaces(org_id,workspace_key,status,provisioning_source,approved_by,approved_at)
  VALUES(v_org.id,v_workspace,'active','initial_registration',NULL,now());
  IF v_workspace<>'clinical_trials' THEN
   INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
   VALUES(v_org.id,v_uid,v_workspace,true,true,true,v_uid)
   ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
  END IF;
 END LOOP;
 INSERT INTO public.jl_user_profiles(user_id,org_id,full_name,workspace_role,active,last_seen)
 VALUES(v_uid,v_org.id,split_part(v_email,'@',1),'admin',true,now())
 ON CONFLICT(user_id) DO UPDATE SET org_id=EXCLUDED.org_id,workspace_role='admin',active=true,last_seen=now();
 RETURN jsonb_build_object('id',v_org.id,'name',v_org.name,'role',v_org.role,'type',v_org.type,'org_code',v_org.org_code,'workspace_keys',to_jsonb(v_keys));
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_register_organisation_multi(text,text[]) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_register_organisation_multi(text,text[]) TO authenticated,service_role;
