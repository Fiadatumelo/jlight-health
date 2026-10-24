-- Improve tenant-fence RLS policy performance by turning request-context
-- current_setting reads into init-plan expressions. This migration is safe to
-- re-run and only updates the known restrictive tenant-fence policies.
DO $$
DECLARE
  p record;
  new_qual text;
  new_check text;
BEGIN
  FOR p IN
    SELECT schemaname, tablename, policyname, cmd, qual, with_check
    FROM pg_policies
    WHERE schemaname = 'public'
      AND policyname IN (
        'jlight_active_membership_fence',
        'jlight_domain_permission_membership_fence'
      )
  LOOP
    new_qual := p.qual;
    new_check := p.with_check;

    IF new_qual IS NOT NULL THEN
      new_qual := replace(new_qual,
        'current_setting(''jlight.organization_id''::text, true)',
        '(SELECT current_setting(''jlight.organization_id''::text, true))');
      new_qual := replace(new_qual,
        'current_setting(''jlight.auth_subject''::text, true)',
        '(SELECT current_setting(''jlight.auth_subject''::text, true))');
    END IF;

    IF new_check IS NOT NULL THEN
      new_check := replace(new_check,
        'current_setting(''jlight.organization_id''::text, true)',
        '(SELECT current_setting(''jlight.organization_id''::text, true))');
      new_check := replace(new_check,
        'current_setting(''jlight.auth_subject''::text, true)',
        '(SELECT current_setting(''jlight.auth_subject''::text, true))');
    END IF;

    IF new_qual IS DISTINCT FROM p.qual OR new_check IS DISTINCT FROM p.with_check THEN
      IF p.cmd <> 'ALL' THEN
        RAISE EXCEPTION 'Unexpected command % for tenant fence policy %.%.%',
          p.cmd, p.schemaname, p.tablename, p.policyname;
      END IF;

      EXECUTE format(
        'ALTER POLICY %I ON %I.%I USING (%s) WITH CHECK (%s)',
        p.policyname, p.schemaname, p.tablename, new_qual, new_check
      );
    END IF;
  END LOOP;
END
$$;
