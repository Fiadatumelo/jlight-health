-- Preserve authenticated RLS policy execution while removing inherited PUBLIC/anon access.
-- This helper is referenced by jl_entries RLS policies. Authenticated must retain
-- EXECUTE for those policies; private schema USAGE remains revoked from API roles.
REVOKE EXECUTE ON FUNCTION private.jlight_entry_domain_access_allowed(uuid, text, jsonb, text)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.jlight_entry_domain_access_allowed(uuid, text, jsonb, text)
  TO authenticated;
