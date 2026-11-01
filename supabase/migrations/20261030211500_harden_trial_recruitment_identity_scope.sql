-- Tighten organisation-consistency constraints and private identity-map boundaries.
-- Safe additive hardening for the governed recruitment foundation.

create unique index if not exists jl_patients_id_org_uidx on public.jl_patients(id,org_id);
create unique index if not exists jl_participants_id_org_uidx on public.jl_participants(id,org_id);
create unique index if not exists jl_trial_studies_id_org_uidx on public.jl_trial_studies(id,organisation_id);

do $block$
begin
  if not exists (select 1 from pg_constraint where conname='jl_trial_recruitment_referrals_study_org_fkey') then
    alter table public.jl_trial_recruitment_referrals
      add constraint jl_trial_recruitment_referrals_study_org_fkey
      foreign key (study_id,org_id)
      references public.jl_trial_studies(id,organisation_id) on delete restrict;
  end if;
  if not exists (select 1 from pg_constraint where conname='jl_trial_recruitment_identity_patient_org_fkey') then
    alter table private.jl_trial_recruitment_identity_links
      add constraint jl_trial_recruitment_identity_patient_org_fkey
      foreign key (hospital_patient_id,org_id)
      references public.jl_patients(id,org_id) on delete restrict;
  end if;
  if not exists (select 1 from pg_constraint where conname='jl_trial_recruitment_identity_participant_org_fkey') then
    alter table private.jl_trial_recruitment_identity_links
      add constraint jl_trial_recruitment_identity_participant_org_fkey
      foreign key (linked_participant_id,org_id)
      references public.jl_participants(id,org_id) on delete restrict;
  end if;
end
$block$;

create index if not exists jl_trial_recruitment_identity_org_idx
  on private.jl_trial_recruitment_identity_links(org_id);
create index if not exists jl_trial_recruitment_identity_patient_idx
  on private.jl_trial_recruitment_identity_links(hospital_patient_id);
create index if not exists jl_trial_recruitment_identity_participant_idx
  on private.jl_trial_recruitment_identity_links(linked_participant_id);
create index if not exists jl_trial_recruitment_identity_created_by_idx
  on private.jl_trial_recruitment_identity_links(created_by);
create index if not exists jl_trial_recruitment_events_actor_idx
  on public.jl_trial_recruitment_events(actor_id);

-- The identity map is reachable only from tightly scoped SECURITY DEFINER
-- routines owned by the database role. Browser roles cannot resolve its schema.
revoke all on schema private from public, anon, authenticated;
revoke all on private.jl_trial_recruitment_identity_links from public, anon, authenticated;

comment on function public.jl_authorise_trial_recruitment(uuid,text,date,text) is
  'SECURITY DEFINER by design: callable only by authenticated users and independently verifies JLIGHT Platform Super Admin before enabling study recruitment.';
comment on function public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) is
  'SECURITY DEFINER by design: enforces Hospital write and Clinical Trials read permissions, tenant and study ownership, active patient, approved ethics metadata and strict minimum-necessary hand-off fields before atomically creating a private identity link and public referral event.';