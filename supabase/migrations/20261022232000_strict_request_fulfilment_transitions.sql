-- Tighten request fulfilment so immutable audit/status fields cannot be edited alongside transitions.
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
    if new.status is distinct from 'pending' then
      raise exception 'New requests must start in pending status' using errcode = '22023';
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
     or new.notes is distinct from old.notes
     or new.ts is distinct from old.ts then
    raise exception 'Request routing and submitted details are immutable' using errcode = '42501';
  end if;

  v_old := to_jsonb(old);
  v_new := to_jsonb(new);

  if v_org_id = old.from_org_id then
    if (v_old - 'card_generated') is distinct from (v_new - 'card_generated') then
      raise exception 'Sending organisation may only update card_generated' using errcode = '42501';
    end if;
    return new;
  end if;

  if v_org_id <> old.target_org_id then
    raise exception 'Organisation is not a participant in this request' using errcode = '42501';
  end if;

  if new.status is distinct from old.status then
    if old.status = 'pending' and new.status = 'accepted' then
      if (v_old - array['status','accepted_at','accepted_by'])
         is distinct from (v_new - array['status','accepted_at','accepted_by']) then
        raise exception 'Accepting a request cannot also change other fields' using errcode = '42501';
      end if;
      new.accepted_at := coalesce(new.accepted_at, now());
      new.accepted_by := auth.uid()::text;
    elsif old.status = 'pending' and new.status = 'rejected' then
      if (v_old - array['status','rejected_at','rejected_by','rejection_reason'])
         is distinct from (v_new - array['status','rejected_at','rejected_by','rejection_reason']) then
        raise exception 'Rejecting a request cannot also change unrelated fields' using errcode = '42501';
      end if;
      new.rejected_at := coalesce(new.rejected_at, now());
      new.rejected_by := auth.uid()::text;
    elsif old.status = 'accepted' and new.status = 'released' then
      if (v_old - array['status','released_at','released_by','released_result','released_unit',
                        'released_interpretation','released_reference_range','card_generated'])
         is distinct from
         (v_new - array['status','released_at','released_by','released_result','released_unit',
                        'released_interpretation','released_reference_range','card_generated']) then
        raise exception 'Releasing a result cannot change unrelated fulfilment or audit fields' using errcode = '42501';
      end if;
      new.released_at := coalesce(new.released_at, now());
      new.released_by := auth.uid()::text;
    else
      raise exception 'Invalid request status transition: % to %', old.status, new.status using errcode = '22023';
    end if;
  else
    if old.status = 'accepted' then
      if (v_old - array['released_result','released_unit','released_interpretation',
                        'released_reference_range','card_generated'])
         is distinct from
         (v_new - array['released_result','released_unit','released_interpretation',
                        'released_reference_range','card_generated']) then
        raise exception 'Accepted requests may only edit draft result fields before release' using errcode = '42501';
      end if;
    elsif (v_old - 'card_generated') is distinct from (v_new - 'card_generated') then
      raise exception 'Only accepted requests may edit draft result fields; other requests may only update card_generated' using errcode = '42501';
    end if;
  end if;

  return new;
end;
$$;
revoke all on function public.jl_guard_request_route() from public, anon, authenticated;
