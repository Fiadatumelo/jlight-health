-- Align owner membership seeding with multi-role membership uniqueness.
-- The original two-column ON CONFLICT target is invalid after migration 011.
BEGIN;
CREATE OR REPLACE FUNCTION public.jl_seed_organisation_owner_membership()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, auth
AS $function$
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
$function$;
REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM anon;
REVOKE ALL ON FUNCTION public.jl_seed_organisation_owner_membership() FROM authenticated;
COMMIT;
