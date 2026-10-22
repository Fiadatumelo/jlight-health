-- SECURITY DEFINER RPCs are exposed through PostgREST. Do not allow anonymous callers.
REVOKE EXECUTE ON FUNCTION public.jl_create_organisation(text, text) FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.jl_current_org_id() FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) FROM PUBLIC, anon;

-- Signed-in users need these functions for workspace creation, tenant resolution,
-- and verified organisation linking. Function bodies must still enforce authorization.
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.jl_current_org_id() TO authenticated;
GRANT EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) TO authenticated;
