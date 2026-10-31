-- When Platform Administration approves a standard workspace for a Clinical-Trials-only
-- organisation, establish the existing organisation owner in the standard membership model
-- before granting owner permissions. Approval remains the only path that activates the entitlement.
CREATE OR REPLACE FUNCTION public.jl_review_workspace_access_request(
 p_request_id uuid,p_decision text,p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE
 v_uid uuid:=auth.uid();
 v_request public.jl_workspace_access_requests%rowtype;
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
 SELECT * INTO v_request FROM public.jl_workspace_access_requests WHERE id=p_request_id FOR UPDATE;
 IF NOT FOUND OR v_request.status<>'pending_review' THEN
  RAISE EXCEPTION 'Only a pending workspace request can be decided' USING ERRCODE='42501';
 END IF;

 UPDATE public.jl_workspace_access_requests
 SET status=p_decision,reviewed_by=v_uid,reviewed_at=now(),decision_reason=btrim(p_reason)
 WHERE id=p_request_id;

 IF p_decision='approved' THEN
  INSERT INTO public.jl_organisation_workspaces
   (org_id,workspace_key,status,provisioning_source,approved_by,approved_at)
  VALUES(v_request.org_id,v_request.requested_workspace,'active','admin_approval',v_uid,now());

  IF v_request.requested_workspace='clinical_trials' THEN
   -- The owner membership was seeded at organisation registration and is the
   -- separate Clinical Trials boundary. No standard workspace permission is granted.
   IF NOT EXISTS (
    SELECT 1 FROM public.jl_org_memberships m
    WHERE m.organisation_id=v_request.org_id AND m.status='active'
      AND m.access_role IN ('owner','org_admin')
   ) THEN
    RAISE EXCEPTION 'No active organisation owner exists for Clinical Trials provisioning' USING ERRCODE='42501';
   END IF;
  ELSE
   -- Preserve owner authority for organisations originally registered only for trials.
   INSERT INTO public.jlight_organization_memberships
    (organization_id,auth_subject,role,active,created_by)
   SELECT m.organisation_id,m.user_id,
     CASE WHEN m.access_role='owner' THEN 'owner' ELSE 'admin' END,
     true,coalesce(m.created_by,m.user_id)
   FROM public.jl_org_memberships m
   WHERE m.organisation_id=v_request.org_id AND m.status='active'
     AND m.access_role IN ('owner','org_admin')
   ON CONFLICT(auth_subject,organization_id) DO UPDATE
    SET role=CASE WHEN public.jlight_organization_memberships.role='owner'
      THEN 'owner' ELSE EXCLUDED.role END,
      active=true;

   INSERT INTO public.jlight_membership_domain_permissions
    (organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
   SELECT m.organization_id,m.auth_subject,v_request.requested_workspace,true,true,true,v_uid
   FROM public.jlight_organization_memberships m
   WHERE m.organization_id=v_request.org_id AND m.active=true AND m.role IN ('owner','admin')
   ON CONFLICT(organization_id,auth_subject,domain) DO UPDATE
    SET can_read=true,can_write=true,can_report=true,granted_by=v_uid,created_at=now();
  END IF;
 END IF;

 INSERT INTO public.jl_workspace_access_request_events
  (request_id,event_type,actor_user_id,previous_status,new_status,reason)
 VALUES(p_request_id,p_decision,v_uid,'pending_review',p_decision,btrim(p_reason));

 RETURN jsonb_build_object('request_id',p_request_id,'decision',p_decision,
  'organisation_id',v_request.org_id,'workspace',v_request.requested_workspace,
  'entitlement_created',p_decision='approved');
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_review_workspace_access_request(uuid,text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_review_workspace_access_request(uuid,text,text) TO authenticated,service_role;
