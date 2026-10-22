-- Staging regression assertions for secure cross-organisation request routing.
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'jl_requests' and column_name = 'target_org_id'
  ) then raise exception 'Missing jl_requests.target_org_id'; end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.jl_requests'::regclass
      and confrelid = 'public.jl_organisations'::regclass
      and contype = 'f'
      and pg_get_constraintdef(oid) like '%target_org_id%'
  ) then raise exception 'target_org_id must reference jl_organisations'; end if;

  if not (select relrowsecurity from pg_class where oid = 'public.jl_requests'::regclass) then
    raise exception 'RLS must be enabled for jl_requests';
  end if;

  if (select count(*) from pg_policies where schemaname = 'public' and tablename = 'jl_requests') <> 3 then
    raise exception 'Expected exactly three organisation-scoped jl_requests policies';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'jl_requests'
      and (roles @> array['public']::name[] or qual like '%target_workspace%' or with_check like '%target_workspace%')
  ) then raise exception 'Legacy/public workspace-scoped request policy remains'; end if;

  if has_table_privilege('anon', 'public.jl_requests', 'select')
     or has_table_privilege('anon', 'public.jl_requests', 'insert')
     or has_table_privilege('authenticated', 'public.jl_requests', 'delete')
     or has_table_privilege('authenticated', 'public.jl_requests', 'truncate') then
    raise exception 'Unexpected browser role privilege on jl_requests';
  end if;

  if not exists (
    select 1 from pg_trigger
    where tgrelid = 'public.jl_requests'::regclass
      and tgname = 'jl_requests_route_guard' and not tgisinternal
  ) then raise exception 'Missing request route/state trigger'; end if;

  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'private' and p.proname = 'jl_current_org_id'
      and p.prosecdef and p.proconfig @> array['search_path=public, pg_temp']
  ) then raise exception 'Tenant resolver must be SECURITY DEFINER with pinned search_path'; end if;
end $$;
