-- Governed compatibility tools for linking existing protocol and participant history.
create table if not exists public.jl_trial_study_events(
 id uuid primary key default gen_random_uuid(),
 organisation_id uuid not null references public.jl_organisations(id) on delete restrict,
 study_id uuid not null,
 event_type text not null check(event_type in ('legacy_protocol_linked')),
 occurred_at timestamptz not null default now(),
 actor_id uuid not null references auth.users(id),
 metadata jsonb not null default '{}'::jsonb,
 foreign key(study_id,organisation_id)
  references public.jl_trial_studies(id,organisation_id) on delete restrict,
 check(jsonb_typeof(metadata)='object' and pg_column_size(metadata)<=2048)
);
create index if not exists jl_trial_study_events_org_study_idx
 on public.jl_trial_study_events(organisation_id,study_id,occurred_at desc);
alter table public.jl_trial_study_events enable row level security;
alter table public.jl_trial_study_events force row level security;
revoke all on public.jl_trial_study_events from anon,authenticated;
grant select on public.jl_trial_study_events to authenticated;
create policy jl_trial_study_events_select on public.jl_trial_study_events
 for select to authenticated
 using((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','read')));

create or replace function public.jl_list_legacy_trial_protocols(p_org_id uuid)
returns table(protocol_id uuid,protocol_number text,title text,status text)
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
  raise exception 'Clinical Trials write permission required' using errcode='42501';
 end if;
 return query
 select p.id,p.protocol_number,p.title,p.status
 from public.jl_protocols p where p.org_id=p_org_id order by p.protocol_number limit 500;
end;
$function$;
revoke all on function public.jl_list_legacy_trial_protocols(uuid) from public,anon;
grant execute on function public.jl_list_legacy_trial_protocols(uuid) to authenticated;

create or replace function public.jl_link_trial_study_legacy_protocol(
 p_org_id uuid,p_study_id uuid,p_protocol_id uuid
) returns void
language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_existing uuid;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
  raise exception 'Clinical Trials write permission required' using errcode='42501';
 end if;
 if not exists(select 1 from public.jl_protocols p where p.id=p_protocol_id and p.org_id=p_org_id) then
  raise exception 'Legacy protocol not found in this organisation' using errcode='P0002';
 end if;
 select legacy_protocol_id into v_existing from public.jl_trial_studies
 where id=p_study_id and organisation_id=p_org_id for update;
 if not found then raise exception 'Study not found' using errcode='P0002'; end if;
 if v_existing is not null and v_existing<>p_protocol_id then
  raise exception 'Study is already linked to another legacy protocol; use a separately reviewed correction workflow' using errcode='23505';
 end if;
 update public.jl_trial_studies set legacy_protocol_id=p_protocol_id,updated_at=now()
 where id=p_study_id and organisation_id=p_org_id and legacy_protocol_id is null;
 if v_existing is null then
  insert into public.jl_trial_study_events(organisation_id,study_id,event_type,actor_id,metadata)
  values(p_org_id,p_study_id,'legacy_protocol_linked',auth.uid(),jsonb_build_object('legacy_protocol_id',p_protocol_id));
 end if;
end;
$function$;
revoke all on function public.jl_link_trial_study_legacy_protocol(uuid,uuid,uuid) from public,anon;
grant execute on function public.jl_link_trial_study_legacy_protocol(uuid,uuid,uuid) to authenticated;

create or replace function public.jl_list_unlinked_legacy_trial_participants(
 p_org_id uuid,p_study_id uuid
) returns table(
 legacy_participant_id uuid,participant_code text,site_code text,status text,
 consent_version text,enrolment_date date,completion_date date,last_visit_date date,next_visit_due date
)
language plpgsql stable security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_protocol_id uuid;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
  raise exception 'Clinical Trials write permission required' using errcode='42501';
 end if;
 select legacy_protocol_id into v_protocol_id from public.jl_trial_studies
 where id=p_study_id and organisation_id=p_org_id;
 if v_protocol_id is null then
  raise exception 'Link this study to its verified legacy protocol before reviewing historical participants' using errcode='22023';
 end if;
 return query
 select lp.id,lp.participant_id,lp.site_id,lp.status,lp.consent_version,
  lp.enrolment_date,lp.completion_date,lp.last_visit_date,lp.next_visit_due
 from public.jl_participants lp
 where lp.org_id=p_org_id and lp.protocol_id=v_protocol_id
  and not exists(select 1 from private.jl_trial_participant_legacy_links x
   where x.legacy_participant_id=lp.id and x.org_id=p_org_id)
 order by lp.participant_id limit 2000;
end;
$function$;
revoke all on function public.jl_list_unlinked_legacy_trial_participants(uuid,uuid) from public,anon;
grant execute on function public.jl_list_unlinked_legacy_trial_participants(uuid,uuid) to authenticated;

comment on function public.jl_list_unlinked_legacy_trial_participants(uuid,uuid) is
 'Returns historical participant codes and operational dates for explicit source-record review. Never returns patient_id, MRN, name or demographics.';
