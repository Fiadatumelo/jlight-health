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

  if (select count(*) from pg_policies where schemaname='public' and tablename='jl_requests') <> 3
     or exists (
       select 1 from pg_policies
       where schemaname='public' and tablename='jl_requests'
         and not (roles @> array['authenticated']::name[])
     ) then raise exception 'jl_requests policies are not the expected authenticated-only set'; end if;

  if not exists (
    select 1 from pg_trigger
    where tgrelid='public.jl_requests'::regclass
      and tgname='jl_requests_route_guard' and not tgisinternal
  ) then raise exception 'Request route/state guard trigger is missing'; end if;

  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname='jl_current_org_id'
      and p.prosecdef and p.proconfig @> array['search_path=public, pg_temp']
  ) then raise exception 'Tenant resolver must be SECURITY DEFINER with pinned search_path'; end if;

  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname='jl_current_org_role'
      and p.prosecdef and p.proconfig @> array['search_path=public, pg_temp']
  ) then raise exception 'Tenant role resolver must have pinned search_path'; end if;

  if exists (
    select 1 from pg_policies
    where schemaname='public'
      and tablename in ('jl_participants','jl_visits','jl_protocols','jl_consents','jl_adverse_events','jl_deviations')
      and (not (roles @> array['authenticated']::name[]) or qual not like '%jl_current_org_role%Trial%' or with_check not like '%jl_current_org_role%Trial%')
  ) then raise exception 'Clinical-trial table policy does not require a Trial organisation'; end if;

  if has_table_privilege('authenticated','public.jl_organisations','truncate')
     or has_table_privilege('authenticated','public.jl_requests','truncate')
     or has_table_privilege('authenticated','public.jl_patients','truncate') then
    raise exception 'Authenticated role retains dangerous TRUNCATE privilege';
  end if;
end $$;
