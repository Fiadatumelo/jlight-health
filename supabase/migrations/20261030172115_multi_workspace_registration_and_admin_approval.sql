-- JLIGHT multi-workspace registration, discovery and Platform Administration approvals.
-- Additive and staging-only. Existing single-path organisations remain supported.
-- All client access is mediated by SECURITY DEFINER RPCs; direct table grants stay revoked.

CREATE TABLE IF NOT EXISTS public.jl_workspace_access_request_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES public.jl_workspace_access_requests(id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK (event_type IN ('submitted','approved','rejected','withdrawn')),
  actor_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  previous_status text,
  new_status text NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.jl_workspace_access_request_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jl_workspace_access_request_events FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.jl_workspace_access_request_events FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.jl_workspace_access_request_events TO service_role;

CREATE OR REPLACE FUNCTION public.jl_register_organisation_multi(
  p_name text,
  p_workspace_keys text[]
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth','extensions'
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_email text;
  v_name text := nullif(btrim(p_name),'');
  v_keys text[];
  v_code text;
  v_org public.jl_organisations%rowtype;
  v_attempt integer := 0;
  v_workspace text;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Verified email-code sign-in is required' USING ERRCODE='42501';
  END IF;
  SELECT lower(email) INTO v_email
  FROM auth.users WHERE id=v_uid AND email_confirmed_at IS NOT NULL;
  IF v_email IS NULL THEN
    RAISE EXCEPTION 'Verify your email before registering an organisation' USING ERRCODE='42501';
  END IF;
  IF v_name IS NULL OR length(v_name) < 2 OR length(v_name) > 180 THEN
    RAISE EXCEPTION 'Organisation name must contain 2 to 180 characters' USING ERRCODE='22023';
  END IF;
  IF p_workspace_keys IS NULL OR cardinality(p_workspace_keys) < 1 OR cardinality(p_workspace_keys) > 4 THEN
    RAISE EXCEPTION 'Select between one and four JLIGHT pathways' USING ERRCODE='22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(p_workspace_keys) x
    WHERE x IS NULL OR x NOT IN ('hospital','laboratory','bioinformatics','clinical_trials')
  ) THEN
    RAISE EXCEPTION 'One or more selected JLIGHT pathways are invalid' USING ERRCODE='22023';
  END IF;
  SELECT array_agg(DISTINCT x ORDER BY x) INTO v_keys FROM unnest(p_workspace_keys) x;
  IF cardinality(v_keys) <> cardinality(p_workspace_keys) THEN
    RAISE EXCEPTION 'Duplicate pathway selections are not allowed' USING ERRCODE='22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.jl_user_profiles p
    WHERE p.user_id=v_uid AND coalesce(p.active,true)=true
  ) OR EXISTS (
    SELECT 1 FROM public.jl_organisations o
    WHERE o.owner_user_id=v_uid AND coalesce(o.active,true)=true
  ) THEN
    RAISE EXCEPTION 'This account is already linked to an active organisation. Sign in to that organisation instead.' USING ERRCODE='23505';
  END IF;

  LOOP
    v_attempt := v_attempt + 1;
    v_code := 'JLI-' || upper(encode(extensions.gen_random_bytes(8),'hex'));
    EXIT WHEN NOT EXISTS (
      SELECT 1 FROM public.jl_organisations o WHERE upper(o.org_code)=v_code
    );
    IF v_attempt >= 10 THEN
      RAISE EXCEPTION 'Could not generate a unique organisation code. Retry registration.';
    END IF;
  END LOOP;

  INSERT INTO public.jl_organisations
    (name,role,type,owner_email,owner_user_id,org_code,active,created_at,updated_at)
  VALUES
    (v_name,'multi','multi',v_email,v_uid,v_code,true,now(),now())
  RETURNING * INTO v_org;

  -- The existing owner-membership trigger creates the authoritative owner records.
  FOREACH v_workspace IN ARRAY v_keys LOOP
    INSERT INTO public.jl_organisation_workspaces
      (org_id,workspace_key,status,provisioning_source,approved_by,approved_at)
    VALUES
      (v_org.id,v_workspace,'active','initial_registration',NULL,now());
    IF v_workspace <> 'clinical_trials' THEN
      INSERT INTO public.jlight_membership_domain_permissions
        (organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
      VALUES
        (v_org.id,v_uid,v_workspace,true,true,true,v_uid)
      ON CONFLICT (organization_id,auth_subject,domain) DO UPDATE
        SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
    END IF;
  END LOOP;

  INSERT INTO public.jl_user_profiles
    (user_id,org_id,full_name,workspace_role,active,last_seen)
  VALUES
    (v_uid,v_org.id,split_part(v_email,'@',1),'admin',true,now())
  ON CONFLICT (user_id) DO UPDATE
    SET org_id=EXCLUDED.org_id,workspace_role='admin',active=true,last_seen=now();

  RETURN jsonb_build_object(
    'id',v_org.id,'name',v_org.name,'role',v_org.role,'type',v_org.type,
    'org_code',v_org.org_code,'workspace_keys',to_jsonb(v_keys)
  );
END;
$function$;

-- Keep the legacy single-path RPC compatible while routing it through the same
-- validated atomic registration transaction. It cannot bypass entitlement creation.
CREATE OR REPLACE FUNCTION public.jl_create_organisation(
  p_name text DEFAULT 'JLIGHT Health Intelligence Platform',
  p_role text DEFAULT 'Laboratory'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_key text;
BEGIN
  v_key := CASE lower(btrim(coalesce(p_role,'')))
    WHEN 'hospital' THEN 'hospital'
    WHEN 'laboratory' THEN 'laboratory'
    WHEN 'bioinformatics' THEN 'bioinformatics'
    WHEN 'trial' THEN 'clinical_trials'
    WHEN 'clinical_trials' THEN 'clinical_trials'
    ELSE NULL
  END;
  IF v_key IS NULL THEN
    RAISE EXCEPTION 'Select a valid JLIGHT pathway' USING ERRCODE='22023';
  END IF;
  RETURN public.jl_register_organisation_multi(p_name,ARRAY[v_key]);
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_list_my_workspaces(p_org_id uuid DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid := auth.uid(); v_result jsonb;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501';
  END IF;
  WITH member_orgs AS (
    SELECT DISTINCT o.id,o.name,o.org_code
    FROM public.jl_organisations o
    WHERE coalesce(o.active,true)=true
      AND (p_org_id IS NULL OR o.id=p_org_id)
      AND (
        EXISTS (SELECT 1 FROM public.jlight_organization_memberships m
          WHERE m.organization_id=o.id AND m.auth_subject=v_uid AND m.active=true)
        OR EXISTS (SELECT 1 FROM public.jl_org_memberships m
          WHERE m.organisation_id=o.id AND m.user_id=v_uid AND m.status='active')
      )
  )
  SELECT coalesce(jsonb_agg(
    jsonb_build_object(
      'organisation_id',o.id,
      'organisation_name',o.name,
      'organisation_code',o.org_code,
      'workspaces',(
        SELECT coalesce(jsonb_agg(jsonb_build_object('key',w.workspace_key,'label',
          CASE w.workspace_key WHEN 'hospital' THEN 'Hospital' WHEN 'laboratory' THEN 'Laboratory'
            WHEN 'bioinformatics' THEN 'Bioinformatics' ELSE 'Clinical Trials' END)
          ORDER BY w.workspace_key),'[]'::jsonb)
        FROM public.jl_organisation_workspaces w
        WHERE w.org_id=o.id AND w.status='active'
          AND (
            (w.workspace_key='clinical_trials' AND EXISTS (
              SELECT 1 FROM public.jl_org_memberships tm
              WHERE tm.organisation_id=o.id AND tm.user_id=v_uid AND tm.status='active'
                AND tm.access_role IN ('owner','org_admin','clinical_trial','reviewer','read_only')
            ))
            OR
            (w.workspace_key<>'clinical_trials' AND EXISTS (
              SELECT 1 FROM public.jlight_organization_memberships mm
              JOIN public.jlight_membership_domain_permissions dp
                ON dp.organization_id=mm.organization_id AND dp.auth_subject=mm.auth_subject
              WHERE mm.organization_id=o.id AND mm.auth_subject=v_uid AND mm.active=true
                AND dp.domain=w.workspace_key AND dp.can_read=true
            ))
          )
      )
    )
    ORDER BY o.name),'[]'::jsonb)
  INTO v_result FROM member_orgs o;
  RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_link_user_to_organisation(
  p_org_id uuid,p_org_code text,p_full_name text DEFAULT NULL,p_workspace_role text DEFAULT 'operator'
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_org public.jl_organisations%rowtype;
  v_can_access boolean;
  v_role text;
  v_name text;
BEGIN
  IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
  SELECT * INTO v_org FROM public.jl_organisations o
  WHERE o.id=p_org_id AND coalesce(o.active,true)=true
    AND upper(btrim(o.org_code))=upper(btrim(coalesce(p_org_code,'')));
  IF NOT FOUND THEN RAISE EXCEPTION 'Organisation code could not be verified' USING ERRCODE='42501'; END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.jl_organisation_workspaces w
    WHERE w.org_id=v_org.id AND w.status='active'
      AND (
        (w.workspace_key='clinical_trials' AND EXISTS (
          SELECT 1 FROM public.jl_org_memberships tm
          WHERE tm.organisation_id=v_org.id AND tm.user_id=v_uid AND tm.status='active'
            AND tm.access_role IN ('owner','org_admin','clinical_trial','reviewer','read_only')
        ))
        OR
        (w.workspace_key<>'clinical_trials' AND EXISTS (
          SELECT 1 FROM public.jlight_organization_memberships mm
          JOIN public.jlight_membership_domain_permissions dp
            ON dp.organization_id=mm.organization_id AND dp.auth_subject=mm.auth_subject
          WHERE mm.organization_id=v_org.id AND mm.auth_subject=v_uid AND mm.active=true
            AND dp.domain=w.workspace_key AND dp.can_read=true
        ))
      )
  ) INTO v_can_access;
  IF NOT v_can_access THEN
    RAISE EXCEPTION 'An active administrator-approved membership and workspace permission are required' USING ERRCODE='42501';
  END IF;

  IF EXISTS (SELECT 1 FROM public.jl_user_profiles p WHERE p.user_id=v_uid AND coalesce(p.active,true)=false) THEN
    RAISE EXCEPTION 'This account is inactive. Contact the organisation administrator.' USING ERRCODE='42501';
  END IF;

  SELECT CASE
    WHEN EXISTS (SELECT 1 FROM public.jl_org_memberships m
      WHERE m.organisation_id=v_org.id AND m.user_id=v_uid AND m.status='active'
        AND m.access_role IN ('owner','org_admin'))
      OR EXISTS (SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id=v_org.id AND m.auth_subject=v_uid AND m.active=true AND m.role IN ('owner','admin'))
      THEN 'admin'
    WHEN EXISTS (SELECT 1 FROM public.jl_org_memberships m
      WHERE m.organisation_id=v_org.id AND m.user_id=v_uid AND m.status='active'
        AND m.access_role IN ('reviewer','read_only'))
      THEN 'viewer'
    ELSE 'operator' END INTO v_role;

  v_name := coalesce(nullif(btrim(p_full_name),''),split_part(coalesce(auth.jwt()->>'email','JLIGHT User'),'@',1));
  INSERT INTO public.jl_user_profiles(user_id,org_id,full_name,workspace_role,active,last_seen)
  VALUES(v_uid,v_org.id,v_name,v_role,true,now())
  ON CONFLICT(user_id) DO UPDATE SET org_id=EXCLUDED.org_id,
    full_name=CASE WHEN nullif(btrim(p_full_name),'') IS NOT NULL THEN EXCLUDED.full_name ELSE public.jl_user_profiles.full_name END,
    workspace_role=EXCLUDED.workspace_role,active=true,last_seen=now();
  RETURN v_org.id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_request_additional_workspace(
  p_org_id uuid,p_workspace text,p_evidence_reference text,p_criteria_version text DEFAULT '2026-10-v1'
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid := auth.uid(); v_request_id uuid;
BEGIN
  IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
  IF p_workspace NOT IN ('hospital','laboratory','bioinformatics','clinical_trials') THEN
    RAISE EXCEPTION 'Invalid workspace' USING ERRCODE='22023';
  END IF;
  IF nullif(btrim(p_evidence_reference),'') IS NULL OR length(p_evidence_reference)>2048 THEN
    RAISE EXCEPTION 'Provide a secure evidence reference (not raw patient or participant data)' USING ERRCODE='22023';
  END IF;
  IF p_criteria_version IS NULL OR length(p_criteria_version)>80 THEN
    RAISE EXCEPTION 'Eligibility criteria version is required' USING ERRCODE='22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.jl_organisations o WHERE o.id=p_org_id AND coalesce(o.active,true)) THEN
    RAISE EXCEPTION 'Active organisation required' USING ERRCODE='42501';
  END IF;
  IF NOT (
    EXISTS (SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id=p_org_id AND m.auth_subject=v_uid AND m.active=true AND m.role IN ('owner','admin'))
    OR EXISTS (SELECT 1 FROM public.jl_org_memberships m
      WHERE m.organisation_id=p_org_id AND m.user_id=v_uid AND m.status='active' AND m.access_role IN ('owner','org_admin'))
  ) THEN
    RAISE EXCEPTION 'Only an active organisation owner or administrator may request an additional pathway' USING ERRCODE='42501';
  END IF;
  IF EXISTS (SELECT 1 FROM public.jl_organisation_workspaces w
    WHERE w.org_id=p_org_id AND w.workspace_key=p_workspace AND w.status='active') THEN
    RAISE EXCEPTION 'This workspace is already enabled' USING ERRCODE='23505';
  END IF;
  INSERT INTO public.jl_workspace_access_requests
    (org_id,requested_workspace,status,evidence_reference,criteria_version,submitted_by)
  VALUES (p_org_id,p_workspace,'pending_review',btrim(p_evidence_reference),p_criteria_version,v_uid)
  RETURNING id INTO v_request_id;
  INSERT INTO public.jl_workspace_access_request_events
    (request_id,event_type,actor_user_id,previous_status,new_status,reason)
  VALUES (v_request_id,'submitted',v_uid,NULL,'pending_review','Eligibility evidence submitted for platform review');
  RETURN v_request_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_list_pending_workspace_requests()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid := auth.uid();
BEGIN
  IF v_uid IS NULL OR NOT public.jl_is_platform_super_admin() THEN
    RAISE EXCEPTION 'JLIGHT Platform Administration access required' USING ERRCODE='42501';
  END IF;
  RETURN coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'request_id',r.id,'organisation_id',r.org_id,'organisation_name',o.name,
      'workspace',r.requested_workspace,'status',r.status,'evidence_reference',r.evidence_reference,
      'criteria_version',r.criteria_version,'submitted_by',r.submitted_by,'submitted_at',r.submitted_at
    ) ORDER BY r.submitted_at)
    FROM public.jl_workspace_access_requests r
    JOIN public.jl_organisations o ON o.id=r.org_id
    WHERE r.status='pending_review'
  ),'[]'::jsonb);
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_review_workspace_access_request(
  p_request_id uuid,p_decision text,p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_request public.jl_workspace_access_requests%rowtype;
  v_workspace_id uuid;
BEGIN
  IF v_uid IS NULL OR NOT public.jl_is_platform_super_admin() THEN
    RAISE EXCEPTION 'JLIGHT Platform Administration access required' USING ERRCODE='42501';
  END IF;
  IF p_decision NOT IN ('approved','rejected') THEN
    RAISE EXCEPTION 'Decision must be approved or rejected' USING ERRCODE='22023';
  END IF;
  IF nullif(btrim(p_reason),'') IS NULL OR length(p_reason)>2000 THEN
    RAISE EXCEPTION 'A decision rationale of up to 2000 characters is required' USING ERRCODE='22023';
  END IF;
  SELECT * INTO v_request FROM public.jl_workspace_access_requests
  WHERE id=p_request_id FOR UPDATE;
  IF NOT FOUND OR v_request.status<>'pending_review' THEN
    RAISE EXCEPTION 'Only a pending workspace request can be decided' USING ERRCODE='42501';
  END IF;

  UPDATE public.jl_workspace_access_requests
  SET status=p_decision,reviewed_by=v_uid,reviewed_at=now(),decision_reason=btrim(p_reason)
  WHERE id=p_request_id;

  IF p_decision='approved' THEN
    INSERT INTO public.jl_organisation_workspaces
      (org_id,workspace_key,status,provisioning_source,approved_by,approved_at)
    VALUES (v_request.org_id,v_request.requested_workspace,'active','admin_approval',v_uid,now())
    RETURNING id INTO v_workspace_id;

    IF v_request.requested_workspace<>'clinical_trials' THEN
      INSERT INTO public.jlight_membership_domain_permissions
        (organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
      SELECT m.organization_id,m.auth_subject,v_request.requested_workspace,true,true,true,v_uid
      FROM public.jlight_organization_memberships m
      WHERE m.organization_id=v_request.org_id AND m.active=true AND m.role='owner'
      ON CONFLICT (organization_id,auth_subject,domain) DO UPDATE
        SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
    END IF;
  END IF;

  INSERT INTO public.jl_workspace_access_request_events
    (request_id,event_type,actor_user_id,previous_status,new_status,reason)
  VALUES (p_request_id,p_decision,v_uid,'pending_review',p_decision,btrim(p_reason));

  RETURN jsonb_build_object('request_id',p_request_id,'decision',p_decision,
    'organisation_id',v_request.org_id,'workspace',v_request.requested_workspace,
    'entitlement_created',p_decision='approved');
END;
$function$;

-- Replace old single-path invitation logic with entitlement-aware checks.
CREATE OR REPLACE FUNCTION public.jl_invite_org_member(p_email text,p_access_role text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE
  v_actor uuid := auth.uid();
  v_org_id uuid;
  v_workspace text;
  v_role text;
  v_target uuid;
  v_target_status text;
BEGIN
  IF v_actor IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
  IF nullif(btrim(p_email),'') IS NULL OR position('@' in p_email)<2 OR length(p_email)>320 THEN
    RAISE EXCEPTION 'Enter a valid email address' USING ERRCODE='22023';
  END IF;
  SELECT p.org_id INTO v_org_id
  FROM public.jl_user_profiles p
  JOIN public.jl_organisations o ON o.id=p.org_id
  WHERE p.user_id=v_actor AND coalesce(p.active,true) AND coalesce(o.active,true)
    AND (
      EXISTS (SELECT 1 FROM public.jlight_organization_memberships m
        WHERE m.organization_id=o.id AND m.auth_subject=v_actor AND m.active=true AND m.role IN ('owner','admin'))
      OR EXISTS (SELECT 1 FROM public.jl_org_memberships m
        WHERE m.organisation_id=o.id AND m.user_id=v_actor AND m.status='active' AND m.access_role IN ('owner','org_admin'))
    )
  LIMIT 1;
  IF v_org_id IS NULL THEN RAISE EXCEPTION 'Active organisation owner or administrator required' USING ERRCODE='42501'; END IF;

  v_role := coalesce(nullif(btrim(p_access_role),''),'read_only');
  v_workspace := CASE v_role
    WHEN 'hospital' THEN 'hospital' WHEN 'laboratory' THEN 'laboratory'
    WHEN 'bioinformatics' THEN 'bioinformatics' WHEN 'clinical_trial' THEN 'clinical_trials'
    WHEN 'reviewer' THEN 'reviewer' WHEN 'read_only' THEN 'read_only' ELSE NULL END;
  IF v_workspace IS NULL THEN RAISE EXCEPTION 'Invalid invitation role' USING ERRCODE='22023'; END IF;
  IF v_workspace IN ('hospital','laboratory','bioinformatics','clinical_trials')
    AND NOT EXISTS (SELECT 1 FROM public.jl_organisation_workspaces w
      WHERE w.org_id=v_org_id AND w.workspace_key=v_workspace AND w.status='active') THEN
    RAISE EXCEPTION 'The organisation does not have this approved workspace' USING ERRCODE='42501';
  END IF;

  SELECT u.id INTO v_target FROM auth.users u WHERE lower(u.email)=lower(btrim(p_email)) LIMIT 1;
  IF v_target IS NULL THEN RAISE EXCEPTION 'The user must first create and verify a JLIGHT email-code account' USING ERRCODE='22023'; END IF;
  IF v_target=v_actor THEN RAISE EXCEPTION 'You cannot invite yourself' USING ERRCODE='22023'; END IF;

  SELECT status INTO v_target_status FROM public.jl_org_memberships
  WHERE organisation_id=v_org_id AND user_id=v_target AND access_role=v_role LIMIT 1;
  IF v_target_status='active' THEN RAISE EXCEPTION 'This user is already an active member' USING ERRCODE='23505'; END IF;

  INSERT INTO public.jl_org_memberships(organisation_id,user_id,access_role,status,created_by)
  VALUES(v_org_id,v_target,v_role,'invited',v_actor)
  ON CONFLICT(organisation_id,user_id,access_role) DO UPDATE
    SET status='invited',created_by=v_actor;
  RETURN jsonb_build_object('success',true,'organisation_id',v_org_id,
    'email',lower(btrim(p_email)),'access_role',v_role,'status','invited');
END;
$function$;

-- On invitation acceptance, activate the exact pre-existing invitation and
-- grant only its path-specific permission. The organisation code never creates membership.
CREATE OR REPLACE FUNCTION public.jl_accept_organisation_invitation(p_org_id uuid,p_org_code text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_confirmed timestamptz;
  v_role text;
  v_count integer;
BEGIN
  IF v_uid IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
  SELECT email_confirmed_at INTO v_confirmed FROM auth.users WHERE id=v_uid;
  IF v_confirmed IS NULL THEN RAISE EXCEPTION 'Verify your email before accepting an invitation' USING ERRCODE='42501'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.jl_organisations o
    WHERE o.id=p_org_id AND coalesce(o.active,true)
      AND upper(btrim(o.org_code))=upper(btrim(coalesce(p_org_code,'')))) THEN
    RAISE EXCEPTION 'Organisation code could not be verified' USING ERRCODE='42501';
  END IF;

  SELECT count(*),min(access_role) INTO v_count,v_role
  FROM public.jl_org_memberships
  WHERE organisation_id=p_org_id AND user_id=v_uid AND status='invited';
  IF v_count=0 THEN
    IF EXISTS (SELECT 1 FROM public.jl_org_memberships
      WHERE organisation_id=p_org_id AND user_id=v_uid AND status='active') THEN RETURN true; END IF;
    RAISE EXCEPTION 'No administrator-approved invitation exists for this account' USING ERRCODE='42501';
  END IF;
  IF v_count<>1 THEN RAISE EXCEPTION 'Multiple invitations exist; ask the administrator to resolve them' USING ERRCODE='42501'; END IF;

  UPDATE public.jl_org_memberships SET status='active'
  WHERE organisation_id=p_org_id AND user_id=v_uid AND status='invited';
  GET DIAGNOSTICS v_count=ROW_COUNT;
  IF v_count<>1 THEN RAISE EXCEPTION 'Invitation could not be activated' USING ERRCODE='42501'; END IF;

  IF v_role IN ('hospital','laboratory','bioinformatics') THEN
    INSERT INTO public.jlight_membership_domain_permissions
      (organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
    VALUES (p_org_id,v_uid,v_role,true,true,true,v_uid)
    ON CONFLICT (organization_id,auth_subject,domain) DO UPDATE
      SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
  ELSIF v_role='clinical_trial' THEN
    -- The separate Clinical Trials membership role remains the access boundary.
    NULL;
  ELSIF v_role='reviewer' OR v_role='read_only' THEN
    -- Reviewer/read-only roles are scoped only where an explicit workspace grant
    -- is added by an organisation administrator; no default cross-path access.
    NULL;
  END IF;
  RETURN true;
END;
$function$;

-- Keep the existing direct table lockdown. Expose only narrow authenticated RPCs.
REVOKE ALL ON FUNCTION public.jl_register_organisation_multi(text,text[]) FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.jl_list_my_workspaces(uuid) FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.jl_request_additional_workspace(uuid,text,text,text) FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.jl_list_pending_workspace_requests() FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.jl_review_workspace_access_request(uuid,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_register_organisation_multi(text,text[]) TO authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.jl_list_my_workspaces(uuid) TO authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.jl_request_additional_workspace(uuid,text,text,text) TO authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.jl_list_pending_workspace_requests() TO authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.jl_review_workspace_access_request(uuid,text,text) TO authenticated,service_role;

REVOKE ALL ON FUNCTION public.jl_create_organisation(text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text,text) TO authenticated,service_role;
REVOKE ALL ON FUNCTION public.jl_link_user_to_organisation(uuid,text,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid,text,text,text) TO authenticated,service_role;
REVOKE ALL ON FUNCTION public.jl_invite_org_member(text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_invite_org_member(text,text) TO authenticated,service_role;
REVOKE ALL ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid,text) TO authenticated,service_role;

COMMENT ON FUNCTION public.jl_register_organisation_multi(text,text[]) IS
'Atomically registers one organisation with one or multiple selected JLIGHT workspace entitlements after verified passwordless email authentication.';
COMMENT ON FUNCTION public.jl_list_my_workspaces(uuid) IS
'Returns only the caller workspaces for which an active organisation entitlement and active member-level read permission both exist.';
COMMENT ON FUNCTION public.jl_review_workspace_access_request(uuid,text,text) IS
'Only an active JLIGHT Platform Super Admin may approve or reject an additional organisation workspace request; approval creates the entitlement and an audit event.';
