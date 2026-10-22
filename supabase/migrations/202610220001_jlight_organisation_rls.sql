-- JLIGHT organisation ownership policies
-- Run through Supabase migrations after reviewing the target project.
-- Keep RLS enabled and restrict organisation writes to the authenticated owner.

ALTER TABLE public.jl_organisations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS orgs_insert ON public.jl_organisations;
DROP POLICY IF EXISTS orgs_insert_authenticated_owner ON public.jl_organisations;
CREATE POLICY orgs_insert_authenticated_owner
  ON public.jl_organisations
  FOR INSERT
  TO authenticated
  WITH CHECK (
    auth.uid() IS NOT NULL
    AND owner_user_id = auth.uid()
  );

DROP POLICY IF EXISTS orgs_select_owner ON public.jl_organisations;
CREATE POLICY orgs_select_owner
  ON public.jl_organisations
  FOR SELECT
  TO authenticated
  USING (owner_user_id = auth.uid());

DROP POLICY IF EXISTS orgs_update_owner ON public.jl_organisations;
CREATE POLICY orgs_update_owner
  ON public.jl_organisations
  FOR UPDATE
  TO authenticated
  USING (owner_user_id = auth.uid())
  WITH CHECK (owner_user_id = auth.uid());

DROP POLICY IF EXISTS orgs_delete_owner ON public.jl_organisations;
CREATE POLICY orgs_delete_owner
  ON public.jl_organisations
  FOR DELETE
  TO authenticated
  USING (owner_user_id = auth.uid());

CREATE UNIQUE INDEX IF NOT EXISTS jl_organisations_org_code_unique
  ON public.jl_organisations (org_code)
  WHERE org_code IS NOT NULL;
