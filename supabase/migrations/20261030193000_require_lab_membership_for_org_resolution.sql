-- Organisation codes identify organisations; they are not access credentials.
-- Resolve a Laboratory organisation only when the caller has active Laboratory read
-- permission. The normalised entitlement, not the legacy organisation role, is authoritative.
CREATE OR REPLACE FUNCTION public.jl_resolve_lab_org(p_org_code text)
RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_count integer; v_id uuid;
BEGIN
 IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING errcode='28000'; END IF;
 IF nullif(btrim(p_org_code),'') IS NULL THEN RAISE EXCEPTION 'Laboratory organisation code is required' USING errcode='22023'; END IF;
 SELECT count(*),min(o.id::text)::uuid INTO v_count,v_id
 FROM public.jl_organisations o
 WHERE upper(btrim(o.org_code))=upper(btrim(p_org_code))
  AND coalesce(o.active,true)=true
  AND EXISTS(SELECT 1 FROM public.jl_organisation_workspaces w
   WHERE w.org_id=o.id AND w.workspace_key='laboratory' AND w.status='active')
  AND public.jlight_has_domain_permission(o.id,'laboratory','read');
 IF v_count<>1 THEN RAISE EXCEPTION 'Laboratory organisation code is invalid or caller is not authorised' USING errcode='42501'; END IF;
 RETURN v_id;
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_resolve_lab_org(text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_resolve_lab_org(text) TO authenticated,service_role;
