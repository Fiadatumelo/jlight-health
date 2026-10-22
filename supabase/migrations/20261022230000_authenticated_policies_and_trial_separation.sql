-- Make JLIGHT tenant policies authenticated-only and enforce the separate clinical-trial workspace.
create or replace function public.jl_current_org_role()
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select o.role
  from public.jl_organisations o
  where o.id = public.jl_current_org_id()
    and coalesce(o.active, true) = true
  limit 1;
$$;
revoke all on function public.jl_current_org_role() from public, anon;
grant execute on function public.jl_current_org_role() to authenticated;

do $$
declare p record;
begin
  for p in
    select schemaname, tablename, policyname
    from pg_policies
    where schemaname = 'public'
      and tablename like 'jl\_%' escape '\'
      and roles @> array['public']::name[]
  loop
    execute format('alter policy %I on %I.%I to authenticated',
      p.policyname, p.schemaname, p.tablename);
  end loop;
end $$;

-- Clinical-trial records are accessible only within an active Trial organisation.
alter policy participants_org on public.jl_participants
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');

alter policy visits_org on public.jl_visits
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');

alter policy protocols_org on public.jl_protocols
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');

alter policy consents_org on public.jl_consents
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');

alter policy ae_org on public.jl_adverse_events
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');

alter policy deviations_org on public.jl_deviations
  to authenticated
  using (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial')
  with check (org_id = public.jl_current_org_id() and public.jl_current_org_role() = 'Trial');
