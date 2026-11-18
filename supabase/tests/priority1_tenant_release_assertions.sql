-- Release assertions for JLIGHT tenant isolation and trial separation.
do $$
begin
  if exists (
    select 1 from pg_policies
    where schemaname='public'
      and tablename like 'jl\_%' escape '\'
      and roles @> array['public']::name[]
  ) then
    raise exception 'JLIGHT domain tables must not have PUBLIC RLS policies';
  end if;

  if exists (
    select 1 from pg_tables t
    where t.schemaname='public' and t.tablename like 'jl\_%' escape '\'
      and has_table_privilege('anon', format('public.%I',t.tablename), 'select')
  ) then raise exception 'Anonymous SELECT privilege remains on a JLIGHT domain table'; end if;

  if exists (
    select 1 from pg_tables t
    where t.schemaname='public' and t.tablename like 'jl\_%' escape '\'
      and has_table_privilege('authenticated', format('public.%I',t.tablename), 'truncate')
  ) then raise exception 'Authenticated TRUNCATE privilege remains on a JLIGHT domain table'; end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid='public.jl_requests'::regclass
      and confrelid='public.jl_organisations'::regclass
      and contype='f' and pg_get_constraintdef(oid) like '%target_org_id%'
  ) then raise exception 'jl_requests.target_org_id foreign key is missing'; end if;

  -- Reconciled 2026-11-18: expect the hardened four-policy set (three
  -- organisation-scoped policies plus the authenticated-only membership fence).
  if (select count(*) from pg_policies where schemaname='public' and tablename='jl_requests') <> 4
     or not exists (
       select 1 from pg_policies
       where schemaname='public' and tablename='jl_requests'
         and policyname='jlight_request_membership_fence' and cmd='ALL'
     )
     or exists (
       select 1 from pg_policies
       where schemaname='public' and tablename='jl_requests'
         and not (roles @> array['authenticated']::name[])
     ) then raise exception 'jl_requests policies are not the expected hardened authenticated-only set'; end if;

  if not exists (
    select 1 from pg_trigger
    where tgrelid='public.jl_requests'::regclass
      and tgname='jl_requests_route_guard' and not tgisinternal
  ) then raise exception 'Request route/state guard trigger is missing'; end if;

  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='private' and p.proname='jl_current_org_id'
      and p.prosecdef and p.proconfig @> array['search_path=public, pg_temp']
  ) then raise exception 'Tenant resolver must be SECURITY DEFINER with pinned search_path'; end if;

  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='private' and p.proname='jl_current_org_role'
      and p.prosecdef and p.proconfig @> array['search_path=public, pg_temp']
  ) then raise exception 'Tenant role resolver must have pinned search_path'; end if;

  -- Reconciled 2026-11-18: the applied staging hardening added a per-table
  -- jlight_tenant_membership_fence ALL policy (jl_is_org_member(org_id)) on top
  -- of the base Trial-organisation policy on every Clinical Trials table. The
  -- hardened expectation is therefore: the base Trial-org policy still present,
  -- the membership fence present, and every policy authenticated-only.
  if exists (
    select 1 from pg_policies
    where schemaname='public'
      and tablename in ('jl_participants','jl_visits','jl_protocols','jl_consents','jl_adverse_events','jl_deviations')
      and (not (roles @> array['authenticated']::name[]))
  ) then raise exception 'Clinical-trial table policy is not authenticated-only'; end if;

  if exists (
    select 1 from unnest(array['jl_participants','jl_visits','jl_protocols','jl_consents','jl_adverse_events','jl_deviations']) t(tablename)
    where not exists (
      select 1 from pg_policies
      where schemaname='public' and tablename=t.tablename
        and policyname='jlight_tenant_membership_fence' and cmd='ALL'
        and qual like '%jl_is_org_member(org_id)%' and with_check like '%jl_is_org_member(org_id)%'
    )
  ) then raise exception 'Clinical-trial table is missing the jlight_tenant_membership_fence policy'; end if;

  if exists (
    select 1 from unnest(array['jl_participants','jl_visits','jl_protocols','jl_consents','jl_adverse_events','jl_deviations']) t(tablename)
    where not exists (
      select 1 from pg_policies
      where schemaname='public' and tablename=t.tablename
        and qual like '%private.jl_current_org_role%Trial%' and with_check like '%private.jl_current_org_role%Trial%'
    )
  ) then raise exception 'Clinical-trial table policy does not require a Trial organisation'; end if;

  if has_table_privilege('authenticated','public.jl_organisations','truncate')
     or has_table_privilege('authenticated','public.jl_requests','truncate')
     or has_table_privilege('authenticated','public.jl_patients','truncate') then
    raise exception 'Authenticated role retains dangerous TRUNCATE privilege';
  end if;

  if has_table_privilege('authenticated','public.jl_user_profiles','update') then
    raise exception 'Authenticated role has blanket profile UPDATE privilege';
  end if;

  if exists (
    select 1 from information_schema.column_privileges
    where table_schema='public' and table_name='jl_user_profiles'
      and grantee='authenticated' and privilege_type='UPDATE'
      and column_name in ('org_id','workspace_role','active','user_id')
  ) then raise exception 'Protected profile identity/role columns are directly updatable'; end if;

  if has_table_privilege('authenticated','public.jl_organisations','update') then
    raise exception 'Authenticated role has blanket organisation UPDATE privilege'; end if;
end $$;
