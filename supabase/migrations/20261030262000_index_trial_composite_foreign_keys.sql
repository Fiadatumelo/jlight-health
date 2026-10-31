-- Cover composite foreign keys on the new Clinical Trials data model.
create index if not exists jl_trial_studies_legacy_protocol_fk_idx
 on public.jl_trial_studies(legacy_protocol_id,organisation_id) where legacy_protocol_id is not null;
create index if not exists jl_trial_participants_study_org_fk_idx
 on public.jl_trial_participants(study_id,organisation_id);
create index if not exists jl_trial_participants_referral_org_fk_idx
 on public.jl_trial_participants(recruitment_referral_id,organisation_id) where recruitment_referral_id is not null;

create index if not exists jl_trial_participant_events_participant_org_study_fk_idx
 on public.jl_trial_participant_events(participant_id,organisation_id,study_id);
create index if not exists jl_trial_participant_events_study_org_fk_idx
 on public.jl_trial_participant_events(study_id,organisation_id);
create index if not exists jl_trial_participant_events_recorded_by_fk_idx
 on public.jl_trial_participant_events(recorded_by);

create index if not exists jl_trial_recruitment_referrals_study_org_fk_idx
 on public.jl_trial_recruitment_referrals(study_id,org_id);
create index if not exists jl_trial_recruitment_referrals_referred_by_fk_idx
 on public.jl_trial_recruitment_referrals(referred_by);
create index if not exists jl_trial_recruitment_referrals_received_by_fk_idx
 on public.jl_trial_recruitment_referrals(received_by) where received_by is not null;

create index if not exists jl_trial_recruitment_events_referral_org_fk_idx
 on public.jl_trial_recruitment_events(referral_id,org_id);
create index if not exists jl_trial_recruitment_events_actor_fk_idx
 on public.jl_trial_recruitment_events(actor_id);

create index if not exists jl_trial_study_events_study_org_fk_idx
 on public.jl_trial_study_events(study_id,organisation_id);
create index if not exists jl_trial_study_events_actor_fk_idx
 on public.jl_trial_study_events(actor_id);

create index if not exists jl_trial_recruitment_identity_referral_org_fk_idx
 on private.jl_trial_recruitment_identity_links(referral_id,org_id);
create index if not exists jl_trial_recruitment_identity_patient_org_fk_idx
 on private.jl_trial_recruitment_identity_links(hospital_patient_id,org_id);
create index if not exists jl_trial_recruitment_identity_participant_org_fk_idx
 on private.jl_trial_recruitment_identity_links(linked_participant_id,org_id) where linked_participant_id is not null;
create index if not exists jl_trial_recruitment_identity_created_by_fk_idx
 on private.jl_trial_recruitment_identity_links(created_by);
create index if not exists jl_trial_recruitment_identity_org_fk_idx
 on private.jl_trial_recruitment_identity_links(org_id);

create index if not exists jl_trial_legacy_links_participant_org_study_fk_idx
 on private.jl_trial_participant_legacy_links(trial_participant_id,org_id,study_id);
create index if not exists jl_trial_legacy_links_legacy_participant_org_fk_idx
 on private.jl_trial_participant_legacy_links(legacy_participant_id,org_id);
create index if not exists jl_trial_legacy_links_verified_by_fk_idx
 on private.jl_trial_participant_legacy_links(verified_by);
