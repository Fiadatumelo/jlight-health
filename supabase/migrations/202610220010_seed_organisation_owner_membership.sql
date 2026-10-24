-- Ensure every newly created organisation gets an owner membership automatically.
-- This keeps the existing organisation-creation RPC compatible with the membership model.
BEGIN;

CREATE OR REPLACE FUNCTION public.jl_seed_organisation_owner_membership()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.owner_user_id IS NOT NULL THEN
    INSERT INTO public.jl_org_memberships
      (organisation_id, user_id, access_role, status, created_by)
    VALUES
      (NEW.id, NEW.owner_user_id, 'owner', 'active', NEW.owner_user_id)
    ON CONFLICT (organisation_id, user_id) DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM PUBLIC;
DROP TRIGGER IF EXISTS jl_organisation_owner_membership_seed ON public.jl_organisations;
CREATE TRIGGER jl_organisation_owner_membership_seed
AFTER INSERT ON public.jl_organisations
FOR EACH ROW EXECUTE FUNCTION public.jl_seed_organisation_owner_membership();

COMMIT;
