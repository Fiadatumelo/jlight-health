-- Tighten exposed organisation RPC execution without breaking signed-in workflows.
-- SECURITY DEFINER is retained only because these functions perform controlled tenant
-- writes/lookups under RLS; bodies validate auth.uid() and constrain allowed roles.
REVOKE ALL ON FUNCTION public.jl_create_organisation(text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text, text) TO authenticated;

REVOKE ALL ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) TO authenticated;

REVOKE ALL ON FUNCTION public.jl_resolve_lab_org(text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_resolve_lab_org(text) TO authenticated;

COMMENT ON FUNCTION public.jl_create_organisation(text, text) IS 'Authenticated organisation setup RPC. SECURITY DEFINER supports controlled tenant creation; the function validates auth.uid() and restricts self-service roles.';
COMMENT ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) IS 'Authenticated organisation membership RPC. SECURITY DEFINER supports controlled tenant linking; the function validates auth.uid(), active organisation, code or ownership, and trial approval.';
COMMENT ON FUNCTION public.jl_resolve_lab_org(text) IS 'Authenticated laboratory organisation resolver. SECURITY DEFINER supports controlled lookup; the function requires auth.uid() and validates a unique active Laboratory organisation.';
