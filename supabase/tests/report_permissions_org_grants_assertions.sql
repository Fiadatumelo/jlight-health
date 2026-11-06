-- Structural release assertions for organisation-configured report permissions.
-- Run against staging after applying the report-permission migration.

DO $assertions$
DECLARE
  v_definition text;
  v_policy_count integer;
BEGIN
  IF to_regprocedure(
    'private.jl_report_access_allowed(text,text,jsonb)'
  ) IS NULL THEN
    RAISE EXCEPTION 'Missing private report permission function';
  END IF;

  v_definition := lower(pg_get_functiondef(
    'private.jl_report_access_allowed(text,text,jsonb)'::regprocedure
  ));

  IF position('jlight_has_domain_permission' in v_definition) = 0 THEN
    RAISE EXCEPTION 'Report permissions do not use organisation domain grants';
  END IF;

  IF position('private.jl_current_org_id()' in v_definition) = 0 THEN
    RAISE EXCEPTION 'Report permissions do not use active organisation context';
  END IF;

  IF position('generate' in v_definition) = 0
     OR position('delete' in v_definition) = 0 THEN
    RAISE EXCEPTION 'Report lifecycle actions are incomplete';
  END IF;

  IF position('workspace_role' in v_definition) > 0
     OR position('supervisor' in v_definition) > 0
     OR position('v_workspace_role' in v_definition) > 0
     OR position('private.jl_current_org_role' in v_definition) > 0 THEN
    RAISE EXCEPTION 'Legacy role-based report gate remains';
  END IF;

  IF position('clinical_trials' in v_definition) = 0
     OR position('clinical trials' in v_definition) = 0 THEN
    RAISE EXCEPTION 'Clinical Trials report isolation checks are missing';
  END IF;

  SELECT count(*) INTO v_policy_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND tablename = 'jl_entries'
    AND policyname IN (
      'jl_entries_reports_select',
      'jl_entries_reports_insert',
      'jl_entries_reports_update',
      'jl_entries_reports_delete'
    )
    AND permissive = 'RESTRICTIVE';

  IF v_policy_count <> 4 THEN
    RAISE EXCEPTION 'Expected four restrictive report policies; found %',
      v_policy_count;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'jl_entries'
      AND policyname = 'jl_entries_reports_insert'
      AND coalesce(with_check, '') ILIKE '%generate%'
  ) THEN
    RAISE EXCEPTION 'Report generation policy does not use generate action';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'jl_entries'
      AND policyname = 'jl_entries_reports_update'
      AND coalesce(qual, '') ILIKE '%write%'
      AND coalesce(with_check, '') ILIKE '%write%'
  ) THEN
    RAISE EXCEPTION 'Report update policy does not require write action';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'jl_entries'
      AND policyname = 'jl_entries_reports_delete'
      AND coalesce(qual, '') ILIKE '%delete%'
  ) THEN
    RAISE EXCEPTION 'Report deletion policy does not use delete action';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename = 'jl_organisations'
      AND indexname = 'jl_organisations_org_code_unique'
      AND indexdef ILIKE '%UNIQUE%'
      AND indexdef ILIKE '%org_code%'
  ) THEN
    RAISE EXCEPTION 'Organisation-code uniqueness index is missing';
  END IF;
END;
$assertions$;