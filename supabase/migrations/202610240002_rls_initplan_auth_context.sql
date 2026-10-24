-- Supabase recommends scalar SELECT wrappers for stable auth/request context
-- functions in RLS predicates. This is a semantics-preserving performance change.
-- Existing wrappers are detected to keep the migration idempotent.
DO $$
DECLARE
  p record;
  new_qual text;
  new_check text;
  stmt text;
BEGIN
  FOR p IN
    SELECT schemaname, tablename, policyname, qual, with_check
    FROM pg_policies
    WHERE schemaname = 'public'
      AND (
        coalesce(qual, '') ~ '(auth\.(uid|jwt|role)\(|current_setting\()'
        OR coalesce(with_check, '') ~ '(auth\.(uid|jwt|role)\(|current_setting\()'
      )
  LOOP
    new_qual := p.qual;
    new_check := p.with_check;

    IF new_qual IS NOT NULL THEN
      IF position('( SELECT auth.uid()' in new_qual) = 0 THEN
        new_qual := replace(new_qual, 'auth.uid()', '(SELECT auth.uid())');
      END IF;
      IF position('( SELECT auth.jwt()' in new_qual) = 0 THEN
        new_qual := replace(new_qual, 'auth.jwt()', '(SELECT auth.jwt())');
      END IF;
      IF position('( SELECT auth.role()' in new_qual) = 0 THEN
        new_qual := replace(new_qual, 'auth.role()', '(SELECT auth.role())');
      END IF;
      IF position('( SELECT current_setting(' in new_qual) = 0 THEN
        new_qual := replace(new_qual,
          'current_setting(''jlight.organization_id''::text, true)',
          '(SELECT current_setting(''jlight.organization_id''::text, true))');
        new_qual := replace(new_qual,
          'current_setting(''jlight.auth_subject''::text, true)',
          '(SELECT current_setting(''jlight.auth_subject''::text, true))');
      END IF;
    END IF;

    IF new_check IS NOT NULL THEN
      IF position('( SELECT auth.uid()' in new_check) = 0 THEN
        new_check := replace(new_check, 'auth.uid()', '(SELECT auth.uid())');
      END IF;
      IF position('( SELECT auth.jwt()' in new_check) = 0 THEN
        new_check := replace(new_check, 'auth.jwt()', '(SELECT auth.jwt())');
      END IF;
      IF position('( SELECT auth.role()' in new_check) = 0 THEN
        new_check := replace(new_check, 'auth.role()', '(SELECT auth.role())');
      END IF;
      IF position('( SELECT current_setting(' in new_check) = 0 THEN
        new_check := replace(new_check,
          'current_setting(''jlight.organization_id''::text, true)',
          '(SELECT current_setting(''jlight.organization_id''::text, true))');
        new_check := replace(new_check,
          'current_setting(''jlight.auth_subject''::text, true)',
          '(SELECT current_setting(''jlight.auth_subject''::text, true))');
      END IF;
    END IF;

    IF new_qual IS DISTINCT FROM p.qual OR new_check IS DISTINCT FROM p.with_check THEN
      stmt := format('ALTER POLICY %I ON %I.%I', p.policyname, p.schemaname, p.tablename);
      IF new_qual IS DISTINCT FROM p.qual THEN
        stmt := stmt || format(' USING (%s)', new_qual);
      END IF;
      IF new_check IS DISTINCT FROM p.with_check THEN
        stmt := stmt || format(' WITH CHECK (%s)', new_check);
      END IF;
      EXECUTE stmt;
    END IF;
  END LOOP;
END
$$;
