-- Remove anonymous execution from sensitive organisation/trial RPCs.
-- Authenticated application flows remain available; service_role remains available
-- for trusted backend operations. SECURITY DEFINER bodies retain their own checks.

REVOKE EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.jl_accept_organisation_invitation(uuid, text) TO authenticated, service_role;

REVOKE EXECUTE ON FUNCTION public.jl_invite_org_member(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.jl_invite_org_member(text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.jl_invite_org_member(text, text) TO authenticated, service_role;

REVOKE EXECUTE ON FUNCTION public.jl_list_trial_members(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.jl_list_trial_members(uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.jl_list_trial_members(uuid) TO authenticated, service_role;

COMMENT ON TABLE public.jl_platform_admins IS
  'Privileged platform-admin registry. Intentionally has no client-facing RLS policies or authenticated/anon table grants; access is mediated by narrowly scoped, authenticated SECURITY DEFINER checks and trusted service_role operations.';
