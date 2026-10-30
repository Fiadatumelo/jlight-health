-- Governed Hospital-to-Clinical-Trial recruitment foundation.
-- Staging/PR only. Does not migrate legacy participant records or expose patient identity.
-- The private identity map is deliberately unavailable to browser roles.

alter table public.jl_trial_studies
  add column if not exists recruitment_enabled boolean not null default false,
  add column if not exists ethics_approval_reference text,
  add column if not exists ethics_approval_date date,
  add column if not exists recruitment_criteria_version text,
  add column if not exists recruitment_authorised_by uuid references auth.users(id),
  add column if not exists recruitment_authorised_at timestamptz;

create table if not exists public.jl_trial_recruitment_referrals (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.jl_organisations(id) on delete restrict,
  study_id uuid not null references public.jl_trial_studies(id) on delete restrict,
  referral_code text not null,
  candidate_summary jsonb not null default '{}'::jsonb,
  criteria_version text not null,
  status text not null default 'referred'
    check (status in ('referred','received','screening','eligible','ineligible','declined','withdrawn','enrolled','closed')),
  referred_by uuid not null references auth.users(id),
  referred_at timestamptz not null default now(),
  received_by uuid references auth.users(id),
  received_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (org_id, referral_code),
  unique (id, org_id),
  check (jsonb_typeof(candidate_summary) = 'object'),
  check (pg_column_size(candidate_summary) <= 4096)
);

create index if not exists jl_trial_recruitment_referrals_study_status_idx
  on public.jl_trial_recruitment_referrals (org_id, study_id, status, referred_at desc);

create table if not exists public.jl_trial_recruitment_events (
  id bigint generated always as identity primary key,
  org_id uuid not null references public.jl_organisations(id) on delete restrict,
  referral_id uuid not null,
  event_type text not null check (event_type in ('referral_created','referral_received','screening_started','screening_outcome_recorded','referral_withdrawn','participant_enrolled','referral_closed')),
  from_status text,
  to_status text,
  actor_id uuid not null references auth.users(id),
  rationale_code text,
  created_at timestamptz not null default now(),
  foreign key (referral_id, org_id)
    references public.jl_trial_recruitment_referrals(id, org_id) on delete restrict
);

create index if not exists jl_trial_recruitment_events_referral_idx
  on public.jl_trial_recruitment_events (org_id, referral_id, created_at);

create schema if not exists private;

create table if not exists private.jl_trial_recruitment_identity_links (
  referral_id uuid primary key,
  org_id uuid not null references public.jl_organisations(id) on delete restrict,
  hospital_patient_id uuid not null references public.jl_patients(id) on delete restrict,
  linked_participant_id uuid references public.jl_participants(id) on delete restrict,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  link_status text not null default 'active'
    check (link_status in ('active','corrected','revoked')),
  purpose text not null default 'protocol_approved_trial_recruitment',
  foreign key (referral_id, org_id)
    references public.jl_trial_recruitment_referrals(id, org_id) on delete restrict
);

alter table public.jl_trial_recruitment_referrals enable row level security;
alter table public.jl_trial_recruitment_referrals force row level security;
alter table public.jl_trial_recruitment_events enable row level security;
alter table public.jl_trial_recruitment_events force row level security;
alter table private.jl_trial_recruitment_identity_links enable row level security;
alter table private.jl_trial_recruitment_identity_links force row level security;

revoke all on public.jl_trial_recruitment_referrals from anon, authenticated;
revoke all on public.jl_trial_recruitment_events from anon, authenticated;
revoke all on private.jl_trial_recruitment_identity_links from public, anon, authenticated;
grant select on public.jl_trial_recruitment_referrals to authenticated;
grant select on public.jl_trial_recruitment_events to authenticated;
grant usage, select on sequence public.jl_trial_recruitment_events_id_seq to authenticated;

drop policy if exists jl_trial_recruitment_referrals_read on public.jl_trial_recruitment_referrals;
create policy jl_trial_recruitment_referrals_read
on public.jl_trial_recruitment_referrals
for select to authenticated
using (
  (select public.jlight_has_domain_permission(org_id,'hospital','read'))
  or
  (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
);

drop policy if exists jl_trial_recruitment_events_read on public.jl_trial_recruitment_events;
create policy jl_trial_recruitment_events_read
on public.jl_trial_recruitment_events
for select to authenticated
using (
  (select public.jlight_has_domain_permission(org_id,'hospital','read'))
  or
  (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
);

create or replace function public.jl_authorise_trial_recruitment(
  p_study_id uuid,
  p_ethics_approval_reference text,
  p_ethics_approval_date date,
  p_criteria_version text
) returns void
language plpgsql
security definer
set search_path = pg_catalog, public, auth
as $function$
declare
  v_org_id uuid;
begin
  if auth.uid() is null or not public.jl_is_platform_super_admin() then
    raise exception 'Independent JLIGHT Platform Administrator approval is required'
      using errcode = '42501';
  end if;
  if nullif(btrim(p_ethics_approval_reference),'') is null
     or p_ethics_approval_date is null
     or p_ethics_approval_date > current_date
     or nullif(btrim(p_criteria_version),'') is null then
    raise exception 'Valid ethics approval reference, approval date and recruitment criteria version are required'
      using errcode = '22023';
  end if;
  select s.organisation_id into v_org_id
  from public.jl_trial_studies s
  where s.id = p_study_id
  for update;
  if v_org_id is null then
    raise exception 'Study not found' using errcode = 'P0002';
  end if;
  update public.jl_trial_studies
  set recruitment_enabled = true,
      ethics_approval_reference = btrim(p_ethics_approval_reference),
      ethics_approval_date = p_ethics_approval_date,
      recruitment_criteria_version = btrim(p_criteria_version),
      recruitment_authorised_by = auth.uid(),
      recruitment_authorised_at = now()
  where id = p_study_id;
end;
$function$;

create or replace function public.jl_create_trial_recruitment_referral(
  p_org_id uuid,
  p_study_id uuid,
  p_hospital_patient_id uuid,
  p_referral_code text,
  p_candidate_summary jsonb,
  p_criteria_version text
) returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public, private, auth
as $function$
declare
  v_referral_id uuid;
  v_patient_org uuid;
  v_study_org uuid;
  v_recruitment_enabled boolean;
  v_criteria_version text;
  v_ethics_reference text;
  v_ethics_date date;
  v_key text;
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  if not public.jlight_has_domain_permission(p_org_id,'hospital','write')
     or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','read') then
    raise exception 'Hospital write and Clinical Trials read permissions are required'
      using errcode = '42501';
  end if;
  if nullif(btrim(p_referral_code),'') is null
     or length(p_referral_code) > 80
     or jsonb_typeof(coalesce(p_candidate_summary,'{}'::jsonb)) <> 'object'
     or pg_column_size(coalesce(p_candidate_summary,'{}'::jsonb)) > 4096 then
    raise exception 'Invalid referral code or candidate summary' using errcode = '22023';
  end if;
  for v_key in select jsonb_object_keys(coalesce(p_candidate_summary,'{}'::jsonb))
  loop
    if v_key not in ('age_band','sex_at_birth','site_code','criteria_match_codes','screening_priority') then
      raise exception 'Candidate summary contains a field not permitted for recruitment hand-off'
        using errcode = '22023';
    end if;
  end loop;
  if coalesce(p_candidate_summary,'{}'::jsonb) ? 'criteria_match_codes'
     and jsonb_typeof(p_candidate_summary->'criteria_match_codes') <> 'array' then
    raise exception 'criteria_match_codes must be an array' using errcode = '22023';
  end if;
  select p.org_id into v_patient_org
  from public.jl_patients p
  where p.id = p_hospital_patient_id and p.org_id = p_org_id and coalesce(p.active,true)=true;
  if v_patient_org is null then
    raise exception 'Hospital patient not found in this organisation' using errcode = 'P0002';
  end if;
  select s.organisation_id, s.recruitment_enabled, s.recruitment_criteria_version,
         s.ethics_approval_reference, s.ethics_approval_date
    into v_study_org, v_recruitment_enabled, v_criteria_version, v_ethics_reference, v_ethics_date
  from public.jl_trial_studies s
  where s.id = p_study_id;
  if v_study_org is distinct from p_org_id
     or v_recruitment_enabled is distinct from true
     or nullif(v_ethics_reference,'') is null
     or v_ethics_date is null or v_ethics_date > current_date
     or v_criteria_version is distinct from p_criteria_version then
    raise exception 'Study recruitment is not independently authorised for this criteria version'
      using errcode = '42501';
  end if;
  insert into public.jl_trial_recruitment_referrals
    (org_id,study_id,referral_code,candidate_summary,criteria_version,referred_by)
  values
    (p_org_id,p_study_id,btrim(p_referral_code),coalesce(p_candidate_summary,'{}'::jsonb),p_criteria_version,auth.uid())
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

revoke all on function public.jl_authorise_trial_recruitment(uuid,text,date,text) from public, anon;
grant execute on function public.jl_authorise_trial_recruitment(uuid,text,date,text) to authenticated;
revoke all on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) from public, anon;
grant execute on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) to authenticated;

comment on table public.jl_trial_recruitment_referrals is
  'Minimum-necessary, study-scoped hospital recruitment hand-offs. Contains no hospital patient identifier.';
comment on table private.jl_trial_recruitment_identity_links is
  'Restricted identity map between a hospital patient and a study recruitment referral. Not exposed to client roles.';
comment on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) is
  'Creates a protocol-authorised recruitment referral and private identity map. Requires verified Hospital write and Clinical Trials read permissions.';
