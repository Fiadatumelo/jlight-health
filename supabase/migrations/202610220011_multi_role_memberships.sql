-- Allow one user to hold multiple explicitly granted roles in one organisation.
-- This is required for legitimate cross-section workflows while preserving
-- the separate, explicitly granted clinical-trial role.
BEGIN;

ALTER TABLE public.jl_org_memberships
  DROP CONSTRAINT IF EXISTS jl_org_memberships_organisation_id_user_id_key;

ALTER TABLE public.jl_org_memberships
  ADD CONSTRAINT jl_org_memberships_org_user_role_key
  UNIQUE (organisation_id, user_id, access_role);

-- This trigger runs only when an organisation is created and seeds the
-- creator's owner membership. Keep the SECURITY DEFINER search path fixed
-- and do not permit direct invocation by client roles.
CREATE OR REPLACE FUNCTION public.jl_seed_organisation_owner_membership()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF NEW.owner_user_id IS NOT NULL THEN
    INSERT INTO public.jl_org_memberships
      (organisation_id, user_id, access_role, status, created_by)
    VALUES
      (NEW.id, NEW.owner_user_id, 'owner', 'active', NEW.owner_user_id)
    ON CONFLICT (organisation_id, user_id, access_role) DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM anon;
REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM authenticated;

COMMIT;
