-- JLIGHT domain persistence contract v1
-- Apply only after reviewing the tenant model and testing on a non-production project.
-- Existing records are preserved; new domain rows are scoped to the active organisation.

alter table public.jl_entries
  add column if not exists org_id uuid references public.jl_organisations(id) on delete cascade,
  add column if not exists domain text;

alter table public.jl_entries
  add constraint jl_entries_domain_allowed
  check (domain is null or domain in (
    'patients','labOrders','results','participants','admissions','bioRuns'
  )) not valid;

create index if not exists jl_entries_org_domain_ts_idx
  on public.jl_entries (org_id, domain, ts desc);

alter table public.jl_entries enable row level security;

drop policy if exists jl_entries_org_select on public.jl_entries;
create policy jl_entries_org_select
  on public.jl_entries for select to authenticated
  using (auth.uid() is not null and org_id = public.jl_current_org_id());

drop policy if exists jl_entries_org_insert on public.jl_entries;
create policy jl_entries_org_insert
  on public.jl_entries for insert to authenticated
  with check (
    auth.uid() is not null
    and user_id = auth.uid()
    and org_id = public.jl_current_org_id()
  );

drop policy if exists jl_entries_org_update on public.jl_entries;
create policy jl_entries_org_update
  on public.jl_entries for update to authenticated
  using (auth.uid() is not null and org_id = public.jl_current_org_id())
  with check (
    auth.uid() is not null
    and user_id = auth.uid()
    and org_id = public.jl_current_org_id()
  );

drop policy if exists jl_entries_org_delete on public.jl_entries;
create policy jl_entries_org_delete
  on public.jl_entries for delete to authenticated
  using (auth.uid() is not null and org_id = public.jl_current_org_id());

-- Intentionally not applied to production by this change. Validate jl_current_org_id()
-- membership semantics and existing RLS behavior in staging before rollout.
