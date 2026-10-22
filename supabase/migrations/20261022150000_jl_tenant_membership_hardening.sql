-- JLIGHT tenant membership and persistence hardening
-- Review and test in a staging Supabase project before applying to production.

create or replace function public.jl_link_user_to_organisation(
  p_org_id uuid,
  p_org_code text,
  p_full_name text default null,
  p_workspace_role text default 'operator'
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v_org public.jl_organisations%rowtype;
  v_name text;
  v_role text;
begin
  if v_uid is null then
    raise exception 'Authentication required' using errcode = '28000';
  end if;
  if p_org_id is null then
    raise exception 'Organisation is required' using errcode = '22023';
  end if;

  select * into v_org
  from public.jl_organisations o
  where o.id = p_org_id
    and (
      (p_org_code is not null and upper(trim(o.org_code)) = upper(trim(p_org_code)))
      or o.owner_user_id = v_uid
    )
  limit 1;

  if not found then
    raise exception 'Organisation code or ownership could not be verified' using errcode = '42501';
  end if;

  v_name := coalesce(nullif(trim(p_full_name), ''), split_part(coalesce(auth.jwt()->>'email', 'JLIGHT User'), '@', 1));
  -- p_workspace_role is retained for RPC signature compatibility only.
  -- Never trust a client-requested role; derive it from verified ownership.
  v_role := case when v_org.owner_user_id = v_uid then 'admin' else 'operator' end;

  insert into public.jl_user_profiles
    (user_id, org_id, full_name, workspace_role, active, last_seen)
  values
    (v_uid, v_org.id, v_name, v_role, true, now())
  on conflict (user_id) do update
    set org_id = excluded.org_id,
        full_name = case when nullif(trim(p_full_name), '') is not null
                         then excluded.full_name else public.jl_user_profiles.full_name end,
        workspace_role = excluded.workspace_role,
        active = true,
        last_seen = now();

  return v_org.id;
end;
$$;

revoke all on function public.jl_link_user_to_organisation(uuid, text, text, text) from public, anon;
grant execute on function public.jl_link_user_to_organisation(uuid, text, text, text) to authenticated;

-- Prevent direct client updates from changing role, organisation, or activation state.
-- Profile membership/role/activation are managed by the SECURITY DEFINER RPC above.
-- Column-level grants are required because RLS alone does not restrict which columns
-- a user may update on their own row.
revoke update on table public.jl_user_profiles from authenticated;
grant update (full_name, employee_id, job_title, qualification, domains, last_seen)
  on table public.jl_user_profiles to authenticated;

-- Trusted tenant linking must happen through the SECURITY DEFINER RPC above.
drop policy if exists profiles_all on public.jl_user_profiles;
drop policy if exists profiles_select_self_or_org on public.jl_user_profiles;
drop policy if exists profiles_insert_unlinked_self on public.jl_user_profiles;
drop policy if exists profiles_update_same_org_self on public.jl_user_profiles;
drop policy if exists profiles_delete_self on public.jl_user_profiles;

create policy profiles_select_self_or_org
  on public.jl_user_profiles for select to authenticated
  using (user_id = auth.uid() or org_id = public.jl_current_org_id());

create policy profiles_insert_unlinked_self
  on public.jl_user_profiles for insert to authenticated
  with check (user_id = auth.uid() and org_id is null);

create policy profiles_update_same_org_self
  on public.jl_user_profiles for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid() and org_id is not distinct from public.jl_current_org_id());

create policy profiles_delete_self
  on public.jl_user_profiles for delete to authenticated
  using (user_id = auth.uid());

-- Do not backfill existing jl_entries rows to a tenant automatically: their ownership
-- cannot be inferred safely. Review and migrate legacy rows separately.
