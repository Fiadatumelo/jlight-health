-- Clinical-trial organisations require controlled provisioning; no self-service role elevation.
create or replace function public.jl_create_organisation(
  p_name text default 'JLIGHT Health Intelligence Platform',
  p_role text default 'Laboratory'
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_name text := coalesce(nullif(btrim(p_name), ''), 'JLIGHT Health Intelligence Platform');
  v_role text := coalesce(nullif(btrim(p_role), ''), 'Laboratory');
  v_code text;
  v_created public.jl_organisations%rowtype;
  v_attempt integer := 0;
begin
  if v_user_id is null then raise exception 'You must be signed in to create an organisation' using errcode = '28000'; end if;
  if v_role not in ('Laboratory', 'Hospital') then
    raise exception 'Clinical-trial organisations require approved provisioning. Choose Laboratory or Hospital for self-service setup.' using errcode = '42501';
  end if;
  if exists (select 1 from public.jl_organisations where owner_user_id = v_user_id) then
    raise exception 'This account already owns an organisation. Sign in to recover it instead.';
  end if;
  loop
    v_attempt := v_attempt + 1;
    v_code := 'JLI-' || upper(substr(md5(gen_random_uuid()::text || clock_timestamp()::text), 1, 4));
    exit when not exists (select 1 from public.jl_organisations where org_code = v_code);
    if v_attempt >= 10 then raise exception 'Could not generate a unique organisation code. Please retry.'; end if;
  end loop;
  insert into public.jl_organisations (name, role, owner_email, owner_user_id, org_code, created_at)
  values (v_name, v_role, coalesce(auth.jwt() ->> 'email', ''), v_user_id, v_code, now())
  returning * into v_created;
  return jsonb_build_object('id', v_created.id, 'name', v_created.name, 'role', v_created.role, 'org_code', v_created.org_code);
end;
$$;
revoke all on function public.jl_create_organisation(text,text) from public, anon;
grant execute on function public.jl_create_organisation(text,text) to authenticated;

create or replace function public.jl_guard_trial_org_role()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if new.role = 'Trial'
     and (tg_op = 'INSERT' or old.role is distinct from new.role)
     and auth.uid() is not null
     and coalesce(auth.role(), '') <> 'service_role' then
    raise exception 'Clinical-trial organisations require approved provisioning' using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function public.jl_guard_trial_org_role() from public, anon, authenticated;
drop trigger if exists jl_guard_trial_org_role on public.jl_organisations;
create trigger jl_guard_trial_org_role
before insert or update of role on public.jl_organisations
for each row execute function public.jl_guard_trial_org_role();

alter policy orgs_insert_authenticated_owner on public.jl_organisations
  with check (auth.uid() is not null and owner_user_id = auth.uid() and role in ('Laboratory','Hospital'));

-- A shared organisation code is not sufficient authorization to join a Trial organisation.
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
  v_profile_exists boolean := false;
begin
  if v_uid is null then raise exception 'Authentication required' using errcode = '28000'; end if;
  if p_org_id is null then raise exception 'Organisation is required' using errcode = '22023'; end if;

  select * into v_org
  from public.jl_organisations o
  where o.id = p_org_id
    and coalesce(o.active, true) = true
    and (
      (p_org_code is not null and upper(trim(o.org_code)) = upper(trim(p_org_code)))
      or o.owner_user_id = v_uid
    )
  limit 1;
  if not found then raise exception 'Organisation code or ownership could not be verified' using errcode = '42501'; end if;

  if v_org.role = 'Trial' and v_org.owner_user_id is distinct from v_uid then
    raise exception 'Clinical-trial membership requires explicit approval; an organisation code alone is not sufficient' using errcode = '42501';
  end if;

  select p.org_id, p.active into v_existing_org, v_existing_active
  from public.jl_user_profiles p where p.user_id = v_uid;
  v_profile_exists := found;

  if v_profile_exists and coalesce(v_existing_active, true) = false then
    raise exception 'This account is inactive. An organisation administrator must reactivate it.' using errcode = '42501';
  end if;
  if v_profile_exists and v_existing_org is not null and v_existing_org <> v_org.id then
    raise exception 'This account is already linked to another organisation. Contact an administrator.' using errcode = '42501';
  end if;

  v_name := coalesce(nullif(trim(p_full_name), ''), split_part(coalesce(auth.jwt()->>'email', 'JLIGHT User'), '@', 1));
  v_role := case when v_org.owner_user_id = v_uid then 'admin' else 'operator' end;

  insert into public.jl_user_profiles (user_id, org_id, full_name, workspace_role, active, last_seen)
  values (v_uid, v_org.id, v_name, v_role, true, now())
  on conflict (user_id) do update
    set org_id = excluded.org_id,
        full_name = case when nullif(trim(p_full_name), '') is not null then excluded.full_name else public.jl_user_profiles.full_name end,
        workspace_role = excluded.workspace_role,
        active = true,
        last_seen = now();

  return v_org.id;
end;
$$;
revoke all on function public.jl_link_user_to_organisation(uuid,text,text,text) from public, anon;
grant execute on function public.jl_link_user_to_organisation(uuid,text,text,text) to authenticated;

-- Remove dangerous table-level DDL privileges and grant only commands covered by RLS policies.
do $$
declare t record; p record; privileges text; cmds text[];
begin
  for t in select tablename from pg_tables where schemaname='public' and tablename like 'jl\_%' escape '\' loop
    execute format('revoke all on table public.%I from anon, authenticated', t.tablename);
    if exists (select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname=t.tablename and c.relrowsecurity) then
      cmds := array[]::text[];
      for p in
        select distinct cmd from pg_policies
        where schemaname='public' and tablename=t.tablename and roles @> array['authenticated']::name[]
      loop
        if p.cmd = 'ALL' then
          cmds := array['SELECT','INSERT','UPDATE','DELETE'];
          exit;
        else
          if p.cmd = 'SELECT' and not ('SELECT'=any(cmds)) then cmds := array_append(cmds,'SELECT'); end if;
          if p.cmd = 'INSERT' and not ('INSERT'=any(cmds)) then cmds := array_append(cmds,'INSERT'); end if;
          if p.cmd = 'UPDATE' and not ('UPDATE'=any(cmds)) then cmds := array_append(cmds,'UPDATE'); end if;
          if p.cmd = 'DELETE' and not ('DELETE'=any(cmds)) then cmds := array_append(cmds,'DELETE'); end if;
        end if;
      end loop;
      if cardinality(cmds)>0 then
        privileges := array_to_string(cmds, ', ');
        execute format('grant %s on table public.%I to authenticated', privileges, t.tablename);
      end if;
    end if;
  end loop;
end $$;
