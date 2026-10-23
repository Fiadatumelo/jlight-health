-- Invitations remain inactive until the invited account is authenticated and email-confirmed.
BEGIN;

ALTER TABLE public.jl_org_memberships
  DROP CONSTRAINT IF EXISTS jl_org_memberships_status_check;
ALTER TABLE public.jl_org_memberships
  ADD CONSTRAINT jl_org_memberships_status_check
  CHECK (status IN ('invited','active','suspended','revoked'));

CREATE OR REPLACE FUNCTION public.jl_accept_organisation_invitations()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, auth
AS $function$
DECLARE
  actor uuid := auth.uid();
  confirmed_at timestamptz;
  activated_count integer;
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;

  SELECT u.email_confirmed_at
    INTO confirmed_at
  FROM auth.users AS u
  WHERE u.id = actor;

  IF confirmed_at IS NULL THEN
    RAISE EXCEPTION 'Confirm your email before accepting organisation invitations' USING ERRCODE = '42501';
  END IF;

  UPDATE public.jl_org_memberships
     SET status = 'active'
   WHERE user_id = actor
     AND status = 'invited';

  GET DIAGNOSTICS activated_count = ROW_COUNT;
  RETURN activated_count;
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_accept_organisation_invitations() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_accept_organisation_invitations() TO authenticated;
COMMIT;
