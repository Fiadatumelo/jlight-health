-- JLIGHT cross-organisation request routing hardening.
-- Staging validation only. Existing rows are not assigned a recipient organisation by guesswork.

alter table public.jl_requests
  add column if not exists target_org_id uuid references public.jl_organisations(id);

create index if not exists jl_requests_from_org_ts_idx
  on public.jl_requests (from_org_id, ts desc);
create index if not exists jl_requests_target_org_ts_idx
  on public.jl_requests (target_org_id, ts desc);

create or replace function public.jl_is_active_lab_org(p_org_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from public.jl_organisations o
    where o.id = p_org_id
      and o.role = 'Laboratory'
      and coalesce(o.active, true) = true
  );
$$;

revoke all on function public.jl_is_active_lab_org(uuid) from public, anon;
grant execute on function public.jl_is_active_lab_org(uuid) to authenticated;

create or replace function public.jl_resolve_lab_org(p_org_code text)
returns uuid
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  v_count integer;
  v_id uuid;
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '28000';
  end if;
  if nullif(trim(p_org_code), '') is null then
    raise exception 'Laboratory organisation code is required' using errcode = '22023';
  end if;

  select count(*), min(o.id::text)::uuid
    into v_count, v_id
  from public.jl_organisations o
  where upper(trim(o.org_code)) = upper(trim(p_org_code))
    and o.role = 'Laboratory'
    and coalesce(o.active, true) = true;

  if v_count <> 1 then
    raise exception 'Laboratory code is invalid or ambiguous' using errcode = '22023';
  end if;
  return v_id;
end;
$$;

revoke all on function public.jl_resolve_lab_org(text) from public, anon;
grant execute on function public.jl_resolve_lab_org(text) to authenticated;

create or replace function public.jl_guard_request_route()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_org_id uuid := public.jl_current_org_id();
  v_old jsonb;
  v_new jsonb;
begin
  if auth.uid() is null or v_org_id is null then
    raise exception 'Authenticated organisation membership required' using errcode = '42501';
  end if;

  if tg_op = 'INSERT' then
    if new.from_org_id is distinct from v_org_id
       or new.from_user_id is distinct from auth.uid()
       or new.target_org_id is null
       or not public.jl_is_active_lab_org(new.target_org_id) then
      raise exception 'Request sender or recipient organisation is invalid' using errcode = '42501';
    end if;
    return new;
  end if;

  if new.jl_id is distinct from old.jl_id
     or new.from_org_id is distinct from old.from_org_id
     or new.target_org_id is distinct from old.target_org_id
     or new.from_user_id is distinct from old.from_user_id
     or new.from_workspace is distinct from old.from_workspace
     or new.target_workspace is distinct from old.target_workspace
     or new.pseudonymous_ref is distinct from old.pseudonymous_ref
     or new.local_ref is distinct from old.local_ref
     or new.test_requested is distinct from old.test_requested
     or new.sample_type is distinct from old.sample_type
     or new.priority is distinct from old.priority
     or new.consent_ref is distinct from old.consent_ref
     or new.patient_id is distinct from old.patient_id
     or new.ts is distinct from old.ts then
    raise exception 'Request routing and submitted details are immutable' using errcode = '42501';
  end if;

  v_old := to_jsonb(old);
  v_new := to_jsonb(new);

  if v_org_id = old.from_org_id then
    -- Sender workspace may only mark its locally generated card as processed.
    if (v_old - 'card_generated') is distinct from (v_new - 'card_generated') then
      raise exception 'Sending organisation may only update card_generated' using errcode = '42501';
    end if;
  elsif v_org_id = old.target_org_id then
    -- Recipient laboratory may manage fulfilment and release fields only.
    if (v_old - array['status','accepted_at','accepted_by','rejected_at','rejected_by',
                      'rejection_reason','released_at','released_by','released_result',
                      'released_unit','released_interpretation','released_reference_range',
                      'card_generated'])
       is distinct from
       (v_new - array['status','accepted_at','accepted_by','rejected_at','rejected_by',
                      'rejection_reason','released_at','released_by','released_result',
                      'released_unit','released_interpretation','released_reference_range',
                      'card_generated']) then
      raise exception 'Laboratory may only update request fulfilment fields' using errcode = '42501';
    end if;
  else
    raise exception 'Organisation is not a participant in this request' using errcode = '42501';
  end if;

  return new;
end;
$$;

drop trigger if exists jl_requests_route_guard on public.jl_requests;
create trigger jl_requests_route_guard
before insert or update on public.jl_requests
for each row execute function public.jl_guard_request_route();

alter table public.jl_requests enable row level security;

drop policy if exists requests_insert on public.jl_requests;
drop policy if exists requests_select on public.jl_requests;
drop policy if exists requests_update on public.jl_requests;
drop policy if exists jl_requests_select_participants on public.jl_requests;
drop policy if exists jl_requests_insert_sender_org on public.jl_requests;
drop policy if exists jl_requests_update_participants on public.jl_requests;

create policy jl_requests_select_participants
  on public.jl_requests for select to authenticated
  using (
    auth.uid() is not null
    and (from_org_id = public.jl_current_org_id()
         or target_org_id = public.jl_current_org_id())
  );

create policy jl_requests_insert_sender_org
  on public.jl_requests for insert to authenticated
  with check (
    auth.uid() is not null
    and from_user_id = auth.uid()
    and from_org_id = public.jl_current_org_id()
    and target_org_id is not null
    and public.jl_is_active_lab_org(target_org_id)
  );

create policy jl_requests_update_participants
  on public.jl_requests for update to authenticated
  using (
    auth.uid() is not null
    and (from_org_id = public.jl_current_org_id()
         or target_org_id = public.jl_current_org_id())
  )
  with check (
    auth.uid() is not null
    and (from_org_id = public.jl_current_org_id()
         or target_org_id = public.jl_current_org_id())
    and public.jl_is_active_lab_org(target_org_id)
  );

revoke all on table public.jl_requests from anon;
grant select, insert, update on table public.jl_requests to authenticated;
