-- Restrictive tenant fences across JLIGHT's organisation-scoped records.
-- Existing permissive role/domain policies remain in force; these restrictive
-- policies add an ANDed active-membership requirement rather than widening access.
BEGIN;

DROP POLICY IF EXISTS jlight_request_membership_fence ON public.jl_requests;
CREATE POLICY jlight_request_membership_fence
  ON public.jl_requests
  AS RESTRICTIVE
  FOR ALL
  TO authenticated
  USING (
    auth.uid() IS NOT NULL
    AND private.jl_current_org_id() IN (from_org_id, target_org_id)
    AND public.jl_is_org_member(private.jl_current_org_id())
  )
  WITH CHECK (
    auth.uid() IS NOT NULL
    AND private.jl_current_org_id() IN (from_org_id, target_org_id)
    AND public.jl_is_org_member(private.jl_current_org_id())
  );
ALTER TABLE public.jl_requests FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.jl_requests FROM anon;

DO $guard$
DECLARE
  r record;
  table_name text;
BEGIN
  FOR r IN
    SELECT c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN information_schema.columns ic
      ON ic.table_schema = n.nspname AND ic.table_name = c.relname
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relname LIKE 'jlight_%'
      AND ic.column_name = 'organization_id'
      AND c.relname NOT IN ('jlight_organization_memberships', 'jlight_membership_domain_permissions')
  LOOP
    table_name := r.table_name;
    EXECUTE format('DROP POLICY IF EXISTS jlight_active_membership_fence ON public.%I', table_name);
    EXECUTE format(
      'CREATE POLICY jlight_active_membership_fence ON public.%I AS RESTRICTIVE FOR ALL TO public USING (
         organization_id = NULLIF(current_setting(''jlight.organization_id'', true), '''')::uuid
         AND EXISTS (
           SELECT 1 FROM public.jlight_organization_memberships m
           WHERE m.organization_id = %I.organization_id
             AND m.auth_subject = NULLIF(current_setting(''jlight.auth_subject'', true), '''')::uuid
             AND m.active = true
         )
       ) WITH CHECK (
         organization_id = NULLIF(current_setting(''jlight.organization_id'', true), '''')::uuid
         AND EXISTS (
           SELECT 1 FROM public.jlight_organization_memberships m
           WHERE m.organization_id = %I.organization_id
             AND m.auth_subject = NULLIF(current_setting(''jlight.auth_subject'', true), '''')::uuid
             AND m.active = true
         )
       )',
      table_name, table_name, table_name
    );
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon', table_name);
  END LOOP;
END
$guard$;

DROP POLICY IF EXISTS jlight_domain_permission_membership_fence ON public.jlight_membership_domain_permissions;
CREATE POLICY jlight_domain_permission_membership_fence
  ON public.jlight_membership_domain_permissions
  AS RESTRICTIVE
  FOR ALL
  TO jlight_runtime
  USING (
    organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid
    AND auth_subject = NULLIF(current_setting('jlight.auth_subject', true), '')::uuid
    AND EXISTS (
      SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id = jlight_membership_domain_permissions.organization_id
        AND m.auth_subject = jlight_membership_domain_permissions.auth_subject
        AND m.active = true
    )
  )
  WITH CHECK (
    organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid
    AND auth_subject = NULLIF(current_setting('jlight.auth_subject', true), '')::uuid
    AND EXISTS (
      SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id = jlight_membership_domain_permissions.organization_id
        AND m.auth_subject = jlight_membership_domain_permissions.auth_subject
        AND m.active = true
    )
  );

COMMIT;
