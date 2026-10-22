-- Manual staging acceptance assertions for JLIGHT Priority 1.
-- Run only AFTER applying the candidate migrations to a non-production staging DB.
-- These checks validate catalog invariants; they do not replace two-tenant auth tests.

do $$
declare
  v_def text;
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='jl_entries' and column_name='org_id'
  ) then
    raise exception 'FAIL: jl_entries.org_id is missing';
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='jl_entries' and column_name='domain'
  ) then
    raise exception 'FAIL: jl_entries.domain is missing';
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid='public.jl_entries'::regclass
      and conname='jl_entries_jl_id_key' and contype='u'
  ) then
    raise exception 'FAIL: global jl_entries jl_id uniqueness was not preserved';
  end if;

  if not exists (
    select 1 from pg_constraint c
    join pg_attribute a on a.attrelid=c.conrelid and a.attnum=any(c.conkey)
    where c.conrelid='public.jl_entries'::regclass
      and c.contype='f' and a.attname='org_id' and c.confdeltype <> 'c'
  ) then
    raise exception 'FAIL: org_id foreign key is missing or cascades deletes';
  end if;

  select pg_get_functiondef('private.jl_current_org_id()'::regprocedure) into v_def;
  if v_def not ilike '%jl_user_profiles%' or v_def not ilike '%auth.uid()%' then
    raise exception 'FAIL: current organisation resolver no longer uses the verified profile';
  end if;

  if has_table_privilege('authenticated','public.jl_user_profiles','UPDATE') then
    raise exception 'FAIL: authenticated retains table-level UPDATE on jl_user_profiles';
  end if;
  if has_column_privilege('authenticated','public.jl_user_profiles','workspace_role','UPDATE')
     or has_column_privilege('authenticated','public.jl_user_profiles','org_id','UPDATE')
     or has_column_privilege('authenticated','public.jl_user_profiles','active','UPDATE') then
    raise exception 'FAIL: authenticated can update a protected profile column';
  end if;
  if not has_column_privilege('authenticated','public.jl_user_profiles','full_name','UPDATE') then
    raise exception 'FAIL: safe profile editing grant is missing';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname='public'
      and tablename in ('alerts','system_health_log')
      and roles @> array['public']::name[]
  ) then
    raise exception 'FAIL: broad PUBLIC policy remains on alerts or system_health_log';
  end if;

  if not (select relrowsecurity from pg_class where oid='public.alerts'::regclass) then
    raise exception 'FAIL: RLS is not enabled on alerts';
  end if;
  if not (select relrowsecurity from pg_class where oid='public.system_health_log'::regclass) then
    raise exception 'FAIL: RLS is not enabled on system_health_log';
  end if;
end $$;

-- Still required separately with two real test organisations and separate accounts:
-- * verify SELECT/INSERT/UPDATE/DELETE cannot cross organisation boundaries;
-- * verify ordinary members cannot self-promote to admin/supervisor;
-- * verify owner membership resolves to admin and invited/code-based members resolve
--   to operator unless an explicit trusted promotion workflow exists;
-- * verify profile save succeeds and role/org/active fields cannot be client-updated;
-- * verify laboratory -> hospital -> bioinformatics patient traceability;
-- * verify clinical-trial data remains a separately authorised journey.
