-- JLIGHT automatic organisation creation and unique code generation.
-- Apply this migration to the Supabase project before deploying/testing the frontend.
-- RLS remains enabled. The function only permits an authenticated user to create
-- an organisation owned by their own auth.uid().

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
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_name text := COALESCE(NULLIF(btrim(p_name), ''), 'JLIGHT Health Intelligence Platform');
  v_role text := COALESCE(NULLIF(btrim(p_role), ''), 'Laboratory');
  v_code text;
  v_created public.jl_organisations%ROWTYPE;
  v_attempt integer := 0;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'You must be signed in to create an organisation';
  END IF;

  IF v_role NOT IN ('Laboratory', 'Trial', 'Hospital') THEN
    RAISE EXCEPTION 'Invalid organisation role';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.jl_organisations WHERE owner_user_id = v_user_id
  ) THEN
    RAISE EXCEPTION 'This account already owns an organisation. Sign in to recover it instead.';
  END IF;

  LOOP
    v_attempt := v_attempt + 1;
    v_code := 'JLI-' || upper(substr(md5(gen_random_uuid()::text || clock_timestamp()::text), 1, 4));
    EXIT WHEN NOT EXISTS (
      SELECT 1 FROM public.jl_organisations WHERE org_code = v_code
    );
    IF v_attempt >= 10 THEN
      RAISE EXCEPTION 'Could not generate a unique organisation code. Please retry.';
    END IF;
  END LOOP;

  INSERT INTO public.jl_organisations
    (name, role, owner_email, owner_user_id, org_code, created_at)
  VALUES
    (v_name, v_role, COALESCE(auth.jwt() ->> 'email', ''), v_user_id, v_code, now())
  RETURNING * INTO v_created;

  RETURN jsonb_build_object(
    'id', v_created.id,
    'name', v_created.name,
    'role', v_created.role,
    'org_code', v_created.org_code
  );
END;
$$;

REVOKE ALL ON FUNCTION public.jl_create_organisation(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text, text) TO authenticated;
