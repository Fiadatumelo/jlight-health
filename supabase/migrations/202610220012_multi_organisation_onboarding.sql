-- Multi-organisation onboarding and workspace switching.
-- Memberships are the authorization source of truth; jl_user_profiles.org_id
-- represents the currently selected workspace only.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS jl_organisations_org_code_unique
  ON public.jl_organisations (org_code)
  WHERE org_code IS NOT NULL;

CREATE OR REPLACE FUNCTION public.jl_create_organisation(
  p_name text DEFAULT 'JLIGHT Health Intelligence Platform',
  p_role text DEFAULT 'Laboratory'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, auth, extensions
AS $function$
DECLARE
  v_user_id uuid := auth.uid();
  v_name text := coalesce(nullif(btrim(p_name), ''), 'JLIGHT Health Intelligence Platform');
  v_role text := coalesce(nullif(btrim(p_role), ''), 'Laboratory');
  v_code text;
  v_created public.jl_organisations%rowtype;
  v_attempt integer := 0;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'You must be signed in to create an organisation'
      USING ERRCODE = '28000';
  END IF;

  IF v_role NOT IN ('Laboratory', 'Hospital') THEN
    RAISE EXCEPTION 'Clinical-trial organisations require approved provisioning'
      USING ERRCODE = '42501';
  END IF;

  -- Do not limit a legitimate account to owning a single organisation.
  -- The trigger creates an owner membership for every new organisation.
  LOOP
    v_attempt := v_attempt + 1;
    v_code := 'JLI-' || upper(encode(extensions.gen_random_bytes(12), 'hex'));
    EXIT WHEN NOT EXISTS (
      SELECT 1 FROM public.jl_organisations o
      WHERE upper(o.org_code) = v_code
    );
    IF v_attempt >= 10 THEN
      RAISE EXCEPTION 'Could not generate a unique organisation code. Please retry.';
    END IF;
  END LOOP;

  INSERT INTO public.jl_organisations
    (name, role, owner_email, owner_user_id, org_code, created_at)
  VALUES
    (v_name, v_role, coalesce(auth.jwt() ->> 'email', ''), v_user_id, v_code, now())
  RETURNING * INTO v_created;

  RETURN jsonb_build_object(
    'id', v_created.id,
    'name', v_created.name,
    'role', v_created.role,
    'org_code', v_created.org_code
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_create_organisation(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.jl_create_organisation(text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text, text) TO authenticated;

CREATE OR REPLACE FUNCTION public.jl_link_user_to_organisation(
  p_org_id uuid,
  p_org_code text,
  p_full_name text DEFAULT NULL,
  p_workspace_role text DEFAULT 'operator'
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, auth
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_org public.jl_organisations%rowtype;
  v_name text;
  v_membership_role text;
  v_existing_status text;
  v_profile_active boolean;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '28000';
  END IF;
  IF p_org_id IS NULL OR nullif(btrim(p_org_code), '') IS NULL THEN
    RAISE EXCEPTION 'Organisation ID and organisation code are required' USING ERRCODE = '22023';
  END IF;

  SELECT o.* INTO v_org
  FROM public.jl_organisations AS o
  WHERE o.id = p_org_id
    AND coalesce(o.active, true)
    AND upper(btrim(o.org_code)) = upper(btrim(p_org_code))
  LIMIT 1;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Organisation code could not be verified' USING ERRCODE = '42501';
  END IF;

  IF v_org.role = 'Trial' AND v_org.owner_user_id IS DISTINCT FROM v_uid THEN
    RAISE EXCEPTION 'Clinical-trial membership requires explicit approval; an organisation code alone is not sufficient'
      USING ERRCODE = '42501';
  END IF;

  SELECT p.active INTO v_profile_active
  FROM public.jl_user_profiles AS p
  WHERE p.user_id = v_uid;

  IF FOUND AND coalesce(v_profile_active, true) = false THEN
    RAISE EXCEPTION 'This account is inactive. An organisation administrator must reactivate it.'
      USING ERRCODE = '42501';
  END IF;

  v_membership_role := CASE
    WHEN v_org.owner_user_id = v_uid THEN 'owner'
    WHEN v_org.role = 'Hospital' THEN 'hospital'
    ELSE 'laboratory'
  END;

  SELECT m.status INTO v_existing_status
  FROM public.jl_org_memberships AS m
  WHERE m.organisation_id = v_org.id
    AND m.user_id = v_uid
    AND m.access_role = v_membership_role
  LIMIT 1;

  IF v_existing_status = 'invited' THEN
    RAISE EXCEPTION 'Accept the confirmed organisation invitation before switching into this workspace'
      USING ERRCODE = '42501';
  ELSIF v_existing_status IN ('suspended', 'revoked') THEN
    RAISE EXCEPTION 'Your membership is not active. Contact the organisation administrator.'
      USING ERRCODE = '42501';
  END IF;

  INSERT INTO public.jl_org_memberships
    (organisation_id, user_id, access_role, status, created_by)
  VALUES
    (v_org.id, v_uid, v_membership_role, 'active', coalesce(v_org.owner_user_id, v_uid))
  ON CONFLICT (organisation_id, user_id, access_role) DO NOTHING;

  v_name := coalesce(
    nullif(btrim(p_full_name), ''),
    split_part(coalesce(auth.jwt() ->> 'email', 'JLIGHT User'), '@', 1)
  );

  -- A profile stores the active workspace, not the complete membership list.
  -- Authorization to every workspace remains enforced by jl_org_memberships.
  INSERT INTO public.jl_user_profiles
    (user_id, org_id, full_name, workspace_role, active, last_seen)
  VALUES
    (v_uid, v_org.id, v_name,
     CASE WHEN v_org.owner_user_id = v_uid THEN 'admin' ELSE 'operator' END,
     true, now())
  ON CONFLICT (user_id) DO UPDATE
    SET org_id = excluded.org_id,
        full_name = CASE
          WHEN nullif(btrim(p_full_name), '') IS NOT NULL THEN excluded.full_name
          ELSE public.jl_user_profiles.full_name
        END,
        workspace_role = excluded.workspace_role,
        active = true,
        last_seen = now();

  RETURN v_org.id;
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.jl_link_user_to_organisation(uuid, text, text, text) TO authenticated;

COMMIT;
