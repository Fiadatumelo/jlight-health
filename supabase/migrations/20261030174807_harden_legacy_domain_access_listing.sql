-- Keep the old one-argument member-access RPC safe for legacy single-path clients.
-- Multi-path organisations must provide an explicit domain to avoid ambiguous listings.
CREATE OR REPLACE FUNCTION public.jlight_list_org_domain_access(p_organization_id uuid)
RETURNS TABLE(
 auth_subject uuid,email text,display_name text,membership_role text,
 membership_active boolean,domain text,can_read boolean,can_write boolean,can_report boolean
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_actor uuid:=auth.uid(); v_count integer; v_domain text;
BEGIN
 IF v_actor IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
 SELECT count(*),min(w.workspace_key) INTO v_count,v_domain
 FROM public.jl_organisation_workspaces w
 WHERE w.org_id=p_organization_id AND w.status='active'
  AND w.workspace_key IN ('hospital','laboratory','bioinformatics');
 IF v_count<>1 THEN
  RAISE EXCEPTION 'An explicit workspace domain is required for multi-path organisations' USING ERRCODE='22023';
 END IF;
 RETURN QUERY
 SELECT * FROM public.jlight_list_org_domain_access(p_organization_id,v_domain);
END;
$function$;
REVOKE ALL ON FUNCTION public.jlight_list_org_domain_access(uuid) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jlight_list_org_domain_access(uuid) TO authenticated,service_role;
