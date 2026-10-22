-- Make the tenant resolver fail closed for inactive users and organisations.
create or replace function public.jl_current_org_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select p.org_id
  from public.jl_user_profiles p
  join public.jl_organisations o on o.id = p.org_id
  where p.user_id = auth.uid()
    and coalesce(p.active, true) = true
    and coalesce(o.active, true) = true
  limit 1;
$$;
revoke all on function public.jl_current_org_id() from public, anon;
grant execute on function public.jl_current_org_id() to authenticated;

-- Never let a shared organisation code silently move an already-linked user
-- between tenants or reactivate a disabled profile.
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
  v_existing_org uuid;
  v_existing_active boolean;
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
    and coalesce(o.active, true) = true
    and (
      (p_org_code is not null and upper(trim(o.org_code)) = upper(trim(p_org_code)))
      or o.owner_user_id = v_uid
    )
  limit 1;

  if not found then
    raise exception 'Organisation code or ownership could not be verified' using errcode = '42501';
  end if;

  select p.org_id, p.active
    into v_existing_org, v_existing_active
  from public.jl_user_profiles p
  where p.user_id = v_uid;

  if found and coalesce(v_existing_active, true) = false then
    raise exception 'This account is inactive. An organisation administrator must reactivate it.' using errcode = '42501';
  end if;
  if found and v_existing_org is not null and v_existing_org <> v_org.id then
    raise exception 'This account is already linked to another organisation. Contact an administrator.' using errcode = '42501';
  end if;

  v_name := coalesce(nullif(trim(p_full_name), ''), split_part(coalesce(auth.jwt()->>'email', 'JLIGHT User'), '@', 1));
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
