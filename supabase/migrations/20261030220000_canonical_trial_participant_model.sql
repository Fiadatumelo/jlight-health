-- Canonical, study-scoped Clinical Trials participant model and operational timeline.
-- Additive compatibility only: legacy records are retained and linked only after review.

create unique index if not exists jl_protocols_id_org_uidx on public.jl_protocols(id,org_id);
create unique index if not exists jl_participants_id_org_uidx on public.jl_participants(id,org_id);
create unique index if not exists jl_trial_studies_id_org_uidx on public.jl_trial_studies(id,organisation_id);
create unique index if not exists jl_trial_participants_id_org_uidx on public.jl_trial_participants(id,organisation_id);
create unique index if not exists jl_trial_participants_id_org_study_uidx
  on public.jl_trial_participants(id,organisation_id,study_id);
create unique index if not exists jl_trial_recruitment_referrals_id_org_study_uidx
  on public.jl_trial_recruitment_referrals(id,org_id,study_id);

alter table public.jl_trial_studies
  add column if not exists legacy_protocol_id uuid,
  add column if not exists site_codes text[] not null default '{}',
  add column if not exists updated_at timestamptz not null default now();

do $block$
begin
  if not exists (select 1 from pg_constraint where conname='jl_trial_studies_legacy_protocol_org_fkey') then
    alter table public.jl_trial_studies add constraint jl_trial_studies_legacy_protocol_org_fkey
      foreign key (legacy_protocol_id,organisation_id)
      references public.jl_protocols(id,org_id) on delete restrict;
  end if;
end
$block$;

create unique index if not exists jl_trial_studies_legacy_protocol_org_uidx
  on public.jl_trial_studies(organisation_id,legacy_protocol_id)
  where legacy_protocol_id is not null;

alter table public.jl_trial_participants
  add column if not exists recruitment_referral_id uuid,
  add column if not exists site_code text,
  add column if not exists screening_number text,
  add column if not exists consent_status text not null default 'not_obtained',
  add column if not exists consent_version text,
  add column if not exists consented_at timestamptz,
  add column if not exists withdrawn_at timestamptz,
  add column if not exists completed_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

alter table public.jl_trial_participants
  add constraint jl_trial_participants_consent_status_check
  check (consent_status in ('not_obtained','pending','obtained','declined','withdrawn'));
alter table public.jl_trial_participants
  add constraint jl_trial_participants_consent_evidence_check
  check (consent_status <> 'obtained' or (consented_at is not null and nullif(btrim(consent_version),'') is not null));

do $block$
begin
  if not exists (select 1 from pg_constraint where conname='jl_trial_participants_study_org_fkey') then
    alter table public.jl_trial_participants add constraint jl_trial_participants_study_org_fkey
      foreign key (study_id,organisation_id)
      references public.jl_trial_studies(id,organisation_id) on delete restrict;
  end if;
  if not exists (select 1 from pg_constraint where conname='jl_trial_participants_referral_org_fkey') then
    alter table public.jl_trial_participants add constraint jl_trial_participants_referral_org_fkey
      foreign key (recruitment_referral_id,organisation_id)
      references public.jl_trial_recruitment_referrals(id,org_id) on delete restrict;
  end if;
end
$block$;

create unique index if not exists jl_trial_participants_referral_uidx
  on public.jl_trial_participants(recruitment_referral_id)
  where recruitment_referral_id is not null;
create index if not exists jl_trial_participants_org_study_status_idx
  on public.jl_trial_participants(organisation_id,study_id,status,created_at desc);

-- Switch the previous optional link from the legacy patient-bearing participant
-- row to the canonical trial participant identity.
alter table private.jl_trial_recruitment_identity_links
  drop constraint if exists jl_trial_recruitment_identity_participant_org_fkey;
alter table private.jl_trial_recruitment_identity_links
  add constraint jl_trial_recruitment_identity_participant_org_fkey
  foreign key (linked_participant_id,org_id)
  references public.jl_trial_participants(id,organisation_id) on delete restrict;

-- Reviewed bridge for legacy protocol/participant/event history. It contains no
-- patient_id. The actual patient-to-participant identity remains in the private
-- recruitment identity map and is never exposed to the Trial workspace.
create table if not exists private.jl_trial_participant_legacy_links (
  trial_participant_id uuid not null,
  org_id uuid not null,
  study_id uuid not null,
  legacy_participant_id uuid not null,
  verified_by uuid not null references auth.users(id),
  verified_at timestamptz not null default now(),
  verification_method text not null check (verification_method in ('manual_source_record_review','approved_migration')),
  primary key (trial_participant_id),
  unique (legacy_participant_id),
  foreign key (trial_participant_id,org_id,study_id)
    references public.jl_trial_participants(id,organisation_id,study_id) on delete restrict,
  foreign key (legacy_participant_id,org_id)
    references public.jl_participants(id,org_id) on delete restrict
);
alter table private.jl_trial_participant_legacy_links enable row level security;
alter table private.jl_trial_participant_legacy_links force row level security;
revoke all on private.jl_trial_participant_legacy_links from public,anon,authenticated;

create index if not exists jl_trial_legacy_links_org_study_idx
  on private.jl_trial_participant_legacy_links(org_id,study_id);
create index if not exists jl_trial_legacy_links_legacy_participant_idx
  on private.jl_trial_participant_legacy_links(legacy_participant_id);

create table if not exists public.jl_trial_participant_events (
  id uuid primary key default gen_random_uuid(),
  organisation_id uuid not null references public.jl_organisations(id) on delete restrict,
  study_id uuid not null,
  participant_id uuid not null,
  event_type text not null check (event_type in (
    'screening_started','screening_outcome','consent_recorded','enrolled',
    'visit_scheduled','visit_completed','visit_missed','adverse_event_recorded',
    'serious_adverse_event_recorded','protocol_deviation_recorded',
    'withdrawn','completed','legacy_record_linked','recruitment_referral_received'
  )),
  occurred_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  status text not null default 'recorded',
  summary text not null,
  source_table text,
  source_record_id text,
  metadata jsonb not null default '{}'::jsonb,
  recorded_by uuid not null references auth.users(id),
  foreign key (participant_id,organisation_id,study_id)
    references public.jl_trial_participants(id,organisation_id,study_id) on delete restrict,
  check (length(btrim(summary)) between 1 and 500),
  check (jsonb_typeof(metadata)='object' and pg_column_size(metadata)<=4096),
  check (source_table is null or source_table in ('jl_visits','jl_consents','jl_adverse_events','jl_deviations','jl_participants','jl_trial_recruitment_referrals'))
);

create index if not exists jl_trial_participant_events_timeline_idx
  on public.jl_trial_participant_events(organisation_id,study_id,participant_id,occurred_at desc,id);
create index if not exists jl_trial_participant_events_type_idx
  on public.jl_trial_participant_events(organisation_id,study_id,event_type,occurred_at desc);

alter table public.jl_trial_participant_events enable row level security;
alter table public.jl_trial_participant_events force row level security;
revoke all on public.jl_trial_participant_events from anon,authenticated;
grant select on public.jl_trial_participant_events to authenticated;

-- Remove role-only policies that predate pathway entitlements. A role alone is
-- not a workspace entitlement or a per-member permission.
drop policy if exists jl_trial_participants_insert on public.jl_trial_participants;
drop policy if exists jl_trial_participants_select on public.jl_trial_participants;
drop policy if exists jl_trial_participants_update on public.jl_trial_participants;
create policy jl_trial_participants_select on public.jl_trial_participants
for select to authenticated
using ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','read')));
create policy jl_trial_participants_insert on public.jl_trial_participants
for insert to authenticated
with check ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write'))
  and created_by=(select auth.uid()));
create policy jl_trial_participants_update on public.jl_trial_participants
for update to authenticated
using ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write')))
with check ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write')));

drop policy if exists jl_trial_studies_insert on public.jl_trial_studies;
drop policy if exists jl_trial_studies_select on public.jl_trial_studies;
drop policy if exists jl_trial_studies_update on public.jl_trial_studies;
create policy jl_trial_studies_select on public.jl_trial_studies
for select to authenticated
using ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','read')));
create policy jl_trial_studies_insert on public.jl_trial_studies
for insert to authenticated
with check ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write'))
  and created_by=(select auth.uid()));
create policy jl_trial_studies_update on public.jl_trial_studies
for update to authenticated
using ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write')))
with check ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','write')));

create policy jl_trial_participant_events_select on public.jl_trial_participant_events
for select to authenticated
using ((select public.jlight_has_domain_permission(organisation_id,'clinical_trials','read')));

-- Referral is visible to its Hospital referrer only with Hospital write, or to
-- authorised Trial readers. A general Hospital read grant is not enough.
drop policy if exists jl_trial_recruitment_referrals_read on public.jl_trial_recruitment_referrals;
create policy jl_trial_recruitment_referrals_read
on public.jl_trial_recruitment_referrals for select to authenticated
using (
  (select public.jlight_has_domain_permission(org_id,'hospital','write'))
  or (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
);
drop policy if exists jl_trial_recruitment_events_read on public.jl_trial_recruitment_events;
create policy jl_trial_recruitment_events_read
on public.jl_trial_recruitment_events for select to authenticated
using (
  (select public.jlight_has_domain_permission(org_id,'hospital','write'))
  or (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
);

-- Legacy participant tables contain patient_id and must not be directly readable
-- through the browser API. Legacy history is read through the reviewed bridge.
revoke all on public.jl_participants,public.jl_visits,public.jl_consents,
  public.jl_adverse_events,public.jl_deviations,public.jl_protocols
from anon,authenticated;

-- A private, backend-only routine provides a bounded, de-identified timeline.
create or replace function private.jl_list_trial_participant_timeline(
  p_org_id uuid,p_participant_id uuid,p_limit integer default 250
) returns table(
  event_id text,event_type text,occurred_at timestamptz,status text,
  summary text,source_table text,source_record_id text,metadata jsonb
)
language plpgsql stable security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_study_id uuid;
begin
  if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','read') then
    raise exception 'Clinical Trials read permission required' using errcode='42501';
  end if;
  if p_limit is null or p_limit<1 or p_limit>500 then
    raise exception 'Timeline limit must be between 1 and 500' using errcode='22023';
  end if;
  select tp.study_id into v_study_id from public.jl_trial_participants tp
  where tp.id=p_participant_id and tp.organisation_id=p_org_id;
  if v_study_id is null then raise exception 'Trial participant not found' using errcode='P0002'; end if;

  return query
  select x.event_id,x.event_type,x.occurred_at,x.status,x.summary,x.source_table,x.source_record_id,x.metadata
  from (
    select e.id::text event_id,e.event_type,e.occurred_at,e.status,e.summary,
           e.source_table,e.source_record_id,e.metadata
    from public.jl_trial_participant_events e
    where e.organisation_id=p_org_id and e.study_id=v_study_id and e.participant_id=p_participant_id
    union all
    select 'legacy:visit:'||v.id::text,'visit_'||coalesce(v.status,'recorded'),
           coalesce(v.actual_date::timestamptz,v.scheduled_date::timestamptz,v.created_at),
           coalesce(v.status,'recorded'),
           'Legacy visit record: '||left(coalesce(v.visit_name,'Visit'),120),
           'jl_visits',v.id::text,
           jsonb_build_object('scheduled_date',v.scheduled_date,'actual_date',v.actual_date,'window_status',v.window_status)
    from private.jl_trial_participant_legacy_links l
    join public.jl_visits v on v.participant_id=l.legacy_participant_id and v.org_id=l.org_id
    where l.trial_participant_id=p_participant_id and l.org_id=p_org_id
    union all
    select 'legacy:consent:'||c.id::text,'consent_recorded',c.consented_at,
           case when coalesce(c.valid,true) then 'valid' else 'superseded_or_invalid' end,
           'Legacy consent record · ICF '||left(c.icf_version,80),
           'jl_consents',c.id::text,jsonb_build_object('icf_version',c.icf_version,'valid',c.valid)
    from private.jl_trial_participant_legacy_links l
    join public.jl_consents c on c.participant_id=l.legacy_participant_id and c.org_id=l.org_id
    where l.trial_participant_id=p_participant_id and l.org_id=p_org_id
    union all
    select 'legacy:ae:'||ae.id::text,
           case when coalesce(ae.is_serious,false) then 'serious_adverse_event_recorded' else 'adverse_event_recorded' end,
           ae.onset_date::timestamptz,
           case when coalesce(ae.sae_overdue,false) then 'overdue' else 'recorded' end,
           'Legacy adverse event record · grade '||coalesce(ae.grade::text,'not recorded'),
           'jl_adverse_events',ae.id::text,
           jsonb_build_object('grade',ae.grade,'is_serious',ae.is_serious,'sae_reported_at',ae.sae_reported_at,'sae_deadline',ae.sae_deadline,'sae_overdue',ae.sae_overdue)
    from private.jl_trial_participant_legacy_links l
    join public.jl_adverse_events ae on ae.participant_id=l.legacy_participant_id and ae.org_id=l.org_id
    where l.trial_participant_id=p_participant_id and l.org_id=p_org_id
    union all
    select 'legacy:deviation:'||d.id::text,'protocol_deviation_recorded',
           d.deviation_date::timestamptz,'recorded',
           'Legacy protocol deviation · '||left(coalesce(d.category,'uncategorised'),80),
           'jl_deviations',d.id::text,jsonb_build_object('category',d.category,'impact',d.impact)
    from private.jl_trial_participant_legacy_links l
    join public.jl_deviations d on d.participant_id=l.legacy_participant_id and d.org_id=l.org_id
    where l.trial_participant_id=p_participant_id and l.org_id=p_org_id
  ) x
  order by x.occurred_at desc nulls last,x.event_id
  limit p_limit;
end;
$function$;

revoke all on function private.jl_list_trial_participant_timeline(uuid,uuid,integer) from public,anon,authenticated;

-- Hospital referral creation requires a Hospital writer and an organisation
-- with the approved Clinical Trials workspace; it does not require the referrer
-- to be a Trial member. Trial-side access is separately checked at receipt.
create or replace function public.jl_create_trial_recruitment_referral(
  p_org_id uuid,p_study_id uuid,p_hospital_patient_id uuid,p_referral_code text,
  p_candidate_summary jsonb,p_criteria_version text
) returns uuid
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare
  v_referral_id uuid; v_patient_org uuid; v_study_org uuid;
  v_recruitment_enabled boolean; v_criteria_version text;
  v_ethics_reference text; v_ethics_date date; v_key text;
begin
  if auth.uid() is null then raise exception 'Authentication required' using errcode='42501'; end if;
  if not public.jlight_has_domain_permission(p_org_id,'hospital','write') then
    raise exception 'Hospital write permission required' using errcode='42501';
  end if;
  if not exists(select 1 from public.jl_organisation_workspaces w
    where w.org_id=p_org_id and w.workspace_key='clinical_trials' and w.status='active') then
    raise exception 'Clinical Trials pathway is not active for this organisation' using errcode='42501';
  end if;
  if nullif(btrim(p_referral_code),'') is null or length(p_referral_code)>80
     or jsonb_typeof(coalesce(p_candidate_summary,'{}'::jsonb))<>'object'
     or pg_column_size(coalesce(p_candidate_summary,'{}'::jsonb))>4096 then
    raise exception 'Invalid referral code or candidate summary' using errcode='22023';
  end if;
  for v_key in select jsonb_object_keys(coalesce(p_candidate_summary,'{}'::jsonb)) loop
    if v_key not in ('age_band','sex_at_birth','site_code','criteria_match_codes','screening_priority') then
      raise exception 'Candidate summary contains a field not permitted for recruitment hand-off' using errcode='22023';
    end if;
  end loop;
  if coalesce(p_candidate_summary,'{}'::jsonb) ? 'criteria_match_codes'
     and jsonb_typeof(p_candidate_summary->'criteria_match_codes')<>'array' then
    raise exception 'criteria_match_codes must be an array' using errcode='22023';
  end if;
  select p.org_id into v_patient_org from public.jl_patients p
  where p.id=p_hospital_patient_id and p.org_id=p_org_id and coalesce(p.active,true)=true;
  if v_patient_org is null then raise exception 'Hospital patient not found in this organisation' using errcode='P0002'; end if;
  select s.organisation_id,s.recruitment_enabled,s.recruitment_criteria_version,
         s.ethics_approval_reference,s.ethics_approval_date
    into v_study_org,v_recruitment_enabled,v_criteria_version,v_ethics_reference,v_ethics_date
  from public.jl_trial_studies s where s.id=p_study_id;
  if v_study_org is distinct from p_org_id or v_recruitment_enabled is distinct from true
     or nullif(v_ethics_reference,'') is null or v_ethics_date is null or v_ethics_date>current_date
     or v_criteria_version is distinct from p_criteria_version then
    raise exception 'Study recruitment is not independently authorised for this criteria version' using errcode='42501';
  end if;
  insert into public.jl_trial_recruitment_referrals
    (org_id,study_id,referral_code,candidate_summary,criteria_version,referred_by)
  values (p_org_id,p_study_id,btrim(p_referral_code),coalesce(p_candidate_summary,'{}'::jsonb),p_criteria_version,auth.uid())
  returning id into v_referral_id;
  insert into private.jl_trial_recruitment_identity_links
    (referral_id,org_id,hospital_patient_id,created_by)
  values (v_referral_id,p_org_id,p_hospital_patient_id,auth.uid());
  insert into public.jl_trial_recruitment_events
    (org_id,referral_id,event_type,to_status,actor_id,rationale_code)
  values (p_org_id,v_referral_id,'referral_created','referred',auth.uid(),'protocol_authorised_recruitment');
  return v_referral_id;
end;
$function$;
revoke all on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) from public,anon;
grant execute on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) to authenticated;

-- Convert a received referral into a study-scoped screening record. Consent
-- remains pending/not obtained until a separate documented consent event.
create or replace function public.jl_create_trial_participant_from_referral(
  p_org_id uuid,p_referral_id uuid,p_participant_code text,p_site_code text default null
) returns uuid
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_study_id uuid; v_status text; v_participant_id uuid;
begin
  if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
    raise exception 'Clinical Trials write permission required' using errcode='42501';
  end if;
  if nullif(btrim(p_participant_code),'') is null or length(p_participant_code)>80 then
    raise exception 'A valid study-specific participant code is required' using errcode='22023';
  end if;
  select r.study_id,r.status into v_study_id,v_status
  from public.jl_trial_recruitment_referrals r
  where r.id=p_referral_id and r.org_id=p_org_id for update;
  if v_study_id is null or v_status not in ('referred','received','screening') then
    raise exception 'Referral is not available for screening' using errcode='42501';
  end if;
  if not exists(select 1 from public.jl_trial_studies s
    where s.id=v_study_id and s.organisation_id=p_org_id and s.status='active') then
    raise exception 'Study is not active' using errcode='42501';
  end if;
  insert into public.jl_trial_participants
    (organisation_id,study_id,participant_code,status,created_by,recruitment_referral_id,site_code,consent_status)
  values (p_org_id,v_study_id,btrim(p_participant_code),'screening',auth.uid(),p_referral_id,nullif(btrim(p_site_code),''),'not_obtained')
  returning id into v_participant_id;
  update public.jl_trial_recruitment_referrals
  set status='screening',received_by=coalesce(received_by,auth.uid()),
      received_at=coalesce(received_at,now()),updated_at=now()
  where id=p_referral_id and org_id=p_org_id;
  update private.jl_trial_recruitment_identity_links
  set linked_participant_id=v_participant_id
  where referral_id=p_referral_id and org_id=p_org_id and link_status='active';
  insert into public.jl_trial_recruitment_events(org_id,referral_id,event_type,from_status,to_status,actor_id,rationale_code)
  values(p_org_id,p_referral_id,'referral_received',v_status,'screening',auth.uid(),'trial_team_screening_created');
  insert into public.jl_trial_participant_events
    (organisation_id,study_id,participant_id,event_type,occurred_at,status,summary,source_table,source_record_id,recorded_by)
  values(p_org_id,v_study_id,v_participant_id,'recruitment_referral_received',now(),'screening',
    'Authorised recruitment referral received; study screening record created.',
    'jl_trial_recruitment_referrals',p_referral_id::text,auth.uid());
  return v_participant_id;
end;
$function$;
revoke all on function public.jl_create_trial_participant_from_referral(uuid,uuid,text,text) from public,anon;
grant execute on function public.jl_create_trial_participant_from_referral(uuid,uuid,text,text) to authenticated;

create or replace function public.jl_record_trial_participant_event(
  p_org_id uuid,p_participant_id uuid,p_event_type text,p_occurred_at timestamptz,
  p_status text,p_summary text,p_metadata jsonb default '{}'::jsonb
) returns uuid
language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_study_id uuid; v_id uuid; v_key text;
begin
  if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
    raise exception 'Clinical Trials write permission required' using errcode='42501';
  end if;
  if p_event_type not in ('screening_started','screening_outcome','consent_recorded','enrolled',
    'visit_scheduled','visit_completed','visit_missed','adverse_event_recorded',
    'serious_adverse_event_recorded','protocol_deviation_recorded','withdrawn','completed') then
    raise exception 'Unsupported Clinical Trials event type' using errcode='22023';
  end if;
  if p_occurred_at is null or nullif(btrim(p_summary),'') is null or length(p_summary)>500
     or jsonb_typeof(coalesce(p_metadata,'{}'::jsonb))<>'object'
     or pg_column_size(coalesce(p_metadata,'{}'::jsonb))>4096 then
    raise exception 'Invalid event date, summary or metadata' using errcode='22023';
  end if;
  for v_key in select jsonb_object_keys(coalesce(p_metadata,'{}'::jsonb)) loop
    if v_key not in ('visit_name','icf_version','consent_status','ae_grade','is_serious',
      'sae_deadline','sae_reported_at','deviation_category','deviation_impact','site_code','outcome_code') then
      raise exception 'Event metadata contains an unsupported field' using errcode='22023';
    end if;
  end loop;
  select study_id into v_study_id from public.jl_trial_participants
  where id=p_participant_id and organisation_id=p_org_id for update;
  if v_study_id is null then raise exception 'Trial participant not found' using errcode='P0002'; end if;
  if p_event_type='consent_recorded' and (
    nullif(p_metadata->>'icf_version','') is null
    or p_metadata->>'consent_status' not in ('obtained','declined','withdrawn')
  ) then raise exception 'Consent events require an ICF version and explicit outcome' using errcode='22023'; end if;
  if p_event_type in ('adverse_event_recorded','serious_adverse_event_recorded')
     and p_metadata ? 'ae_grade'
     and (p_metadata->>'ae_grade') !~ '^[1-5]$' then
    raise exception 'AE grade must be between 1 and 5' using errcode='22023';
  end if;
  insert into public.jl_trial_participant_events
    (organisation_id,study_id,participant_id,event_type,occurred_at,status,summary,metadata,recorded_by)
  values(p_org_id,v_study_id,p_participant_id,p_event_type,p_occurred_at,
    coalesce(nullif(btrim(p_status),''),'recorded'),btrim(p_summary),coalesce(p_metadata,'{}'::jsonb),auth.uid())
  returning id into v_id;
  if p_event_type='consent_recorded' then
    update public.jl_trial_participants
    set consent_status=p_metadata->>'consent_status',
        consent_version=p_metadata->>'icf_version',
        consented_at=case when p_metadata->>'consent_status'='obtained' then p_occurred_at else consented_at end,
        updated_at=now()
    where id=p_participant_id and organisation_id=p_org_id;
  elsif p_event_type='enrolled' then
    if not exists(select 1 from public.jl_trial_participants
      where id=p_participant_id and organisation_id=p_org_id and consent_status='obtained') then
      raise exception 'Documented informed consent is required before enrolment' using errcode='42501';
    end if;
    update public.jl_trial_participants set status='enrolled',updated_at=now()
      where id=p_participant_id and organisation_id=p_org_id;
  elsif p_event_type='withdrawn' then
    update public.jl_trial_participants set status='withdrawn',withdrawn_at=p_occurred_at,updated_at=now()
      where id=p_participant_id and organisation_id=p_org_id;
  elsif p_event_type='completed' then
    update public.jl_trial_participants set status='completed',completed_at=p_occurred_at,updated_at=now()
      where id=p_participant_id and organisation_id=p_org_id;
  end if;
  return v_id;
end;
$function$;
revoke all on function public.jl_record_trial_participant_event(uuid,uuid,text,timestamptz,text,text,jsonb) from public,anon;
grant execute on function public.jl_record_trial_participant_event(uuid,uuid,text,timestamptz,text,text,jsonb) to authenticated;

-- A trial member may link a legacy participant only after checking the source
-- records and mapping its protocol to the canonical study. No demographic auto-match.
create or replace function private.jl_verify_legacy_trial_participant_link(
  p_org_id uuid,p_trial_participant_id uuid,p_legacy_participant_id uuid,p_method text
) returns void
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_study uuid; v_protocol uuid; v_legacy_protocol uuid;
begin
  if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
    raise exception 'Clinical Trials write permission required' using errcode='42501';
  end if;
  if p_method not in ('manual_source_record_review','approved_migration') then
    raise exception 'A governed legacy-link verification method is required' using errcode='22023';
  end if;
  select tp.study_id,s.legacy_protocol_id into v_study,v_protocol
  from public.jl_trial_participants tp
  join public.jl_trial_studies s on s.id=tp.study_id and s.organisation_id=tp.organisation_id
  where tp.id=p_trial_participant_id and tp.organisation_id=p_org_id;
  select lp.protocol_id into v_legacy_protocol from public.jl_participants lp
  where lp.id=p_legacy_participant_id and lp.org_id=p_org_id;
  if v_study is null or v_protocol is null or v_legacy_protocol is distinct from v_protocol then
    raise exception 'Legacy participant protocol is not explicitly mapped to this study' using errcode='42501';
  end if;
  insert into private.jl_trial_participant_legacy_links
    (trial_participant_id,org_id,study_id,legacy_participant_id,verified_by,verification_method)
  values(p_trial_participant_id,p_org_id,v_study,p_legacy_participant_id,auth.uid(),p_method);
  insert into public.jl_trial_participant_events
    (organisation_id,study_id,participant_id,event_type,occurred_at,status,summary,source_table,source_record_id,recorded_by)
  values(p_org_id,v_study,p_trial_participant_id,'legacy_record_linked',now(),'verified',
    'Historical trial events linked after authorised source-record review.',
    'jl_participants',p_legacy_participant_id::text,auth.uid());
end;
$function$;
revoke all on function private.jl_verify_legacy_trial_participant_link(uuid,uuid,uuid,text) from public,anon,authenticated;

comment on table public.jl_trial_participants is
  'Canonical study-scoped trial participant identity. Contains participant code only, never a hospital patient identifier.';
comment on table public.jl_trial_participant_events is
  'Append-only, participant- and study-scoped Clinical Trials timeline. Free-text clinical narratives are not stored here.';
comment on table private.jl_trial_participant_legacy_links is
  'Restricted, manually verified bridge to legacy participant records for historical event traceability.';
