-- Make human screening outcomes and consent evidence explicit in the canonical participant lifecycle.
alter table public.jl_trial_participants
 add column if not exists consent_record_reference text;

create or replace function public.jl_record_trial_participant_event(
 p_org_id uuid,p_participant_id uuid,p_event_type text,p_occurred_at timestamptz,
 p_status text,p_summary text,p_metadata jsonb default '{}'::jsonb
) returns uuid
language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_study_id uuid;v_event_id uuid;v_referral_id uuid;v_key text;v_outcome text;
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
  if v_key not in ('visit_name','icf_version','consent_status','consent_record_reference',
   'consent_witness','ae_grade','is_serious','sae_deadline','sae_reported_at',
   'deviation_category','deviation_impact','site_code','outcome_code') then
   raise exception 'Event metadata contains an unsupported field' using errcode='22023';
  end if;
 end loop;
 select study_id,recruitment_referral_id into v_study_id,v_referral_id
 from public.jl_trial_participants
 where id=p_participant_id and organisation_id=p_org_id for update;
 if v_study_id is null then raise exception 'Trial participant not found' using errcode='P0002'; end if;

 if p_event_type='consent_recorded' then
  if nullif(btrim(p_metadata->>'icf_version'),'') is null
   or p_metadata->>'consent_status' not in ('obtained','declined','withdrawn') then
   raise exception 'Consent events require an ICF version and explicit documented outcome' using errcode='22023';
  end if;
  if p_metadata->>'consent_status'='obtained'
   and (nullif(btrim(p_metadata->>'consent_record_reference'),'') is null
    or length(p_metadata->>'consent_record_reference')>200) then
   raise exception 'Obtained consent requires a controlled source-document reference' using errcode='22023';
  end if;
 elsif p_event_type='screening_outcome' then
  v_outcome:=p_metadata->>'outcome_code';
  if v_outcome not in ('eligible_for_consent','not_eligible','needs_review') then
   raise exception 'Screening outcome must be eligible_for_consent, not_eligible or needs_review' using errcode='22023';
  end if;
 elsif p_event_type in ('adverse_event_recorded','serious_adverse_event_recorded')
  and p_metadata ? 'ae_grade' and (p_metadata->>'ae_grade') !~ '^[1-5]$' then
  raise exception 'AE grade must be between 1 and 5' using errcode='22023';
 end if;

 insert into public.jl_trial_participant_events
  (organisation_id,study_id,participant_id,event_type,occurred_at,status,summary,metadata,recorded_by)
 values(p_org_id,v_study_id,p_participant_id,p_event_type,p_occurred_at,
  coalesce(nullif(btrim(p_status),''),'recorded'),btrim(p_summary),coalesce(p_metadata,'{}'::jsonb),auth.uid())
 returning id into v_event_id;

 if p_event_type='consent_recorded' then
  update public.jl_trial_participants
  set consent_status=p_metadata->>'consent_status',
      consent_version=p_metadata->>'icf_version',
      consent_record_reference=nullif(btrim(p_metadata->>'consent_record_reference'),''),
      consented_at=case when p_metadata->>'consent_status'='obtained' then p_occurred_at else consented_at end,
      updated_at=now()
  where id=p_participant_id and organisation_id=p_org_id;
 elsif p_event_type='screening_outcome' then
  if v_outcome='not_eligible' then
   update public.jl_trial_participants set status='screen_failed',updated_at=now()
    where id=p_participant_id and organisation_id=p_org_id;
   if v_referral_id is not null then
    update public.jl_trial_recruitment_referrals set status='ineligible',updated_at=now()
     where id=v_referral_id and org_id=p_org_id;
   end if;
  elsif v_outcome='eligible_for_consent' and v_referral_id is not null then
   update public.jl_trial_recruitment_referrals set status='eligible',updated_at=now()
    where id=v_referral_id and org_id=p_org_id;
  end if;
 elsif p_event_type='enrolled' then
  if not exists(select 1 from public.jl_trial_participants
    where id=p_participant_id and organisation_id=p_org_id
     and consent_status='obtained' and consented_at is not null
     and consent_record_reference is not null and consent_version is not null) then
   raise exception 'Verified informed-consent evidence is required before enrolment' using errcode='42501';
  end if;
  update public.jl_trial_participants set status='enrolled',updated_at=now()
   where id=p_participant_id and organisation_id=p_org_id;
  if v_referral_id is not null then
   update public.jl_trial_recruitment_referrals set status='enrolled',updated_at=now()
    where id=v_referral_id and org_id=p_org_id;
  end if;
 elsif p_event_type='withdrawn' then
  update public.jl_trial_participants set status='withdrawn',withdrawn_at=p_occurred_at,updated_at=now()
   where id=p_participant_id and organisation_id=p_org_id;
  if v_referral_id is not null then
   update public.jl_trial_recruitment_referrals set status='withdrawn',updated_at=now()
    where id=v_referral_id and org_id=p_org_id;
  end if;
 elsif p_event_type='completed' then
  update public.jl_trial_participants set status='completed',completed_at=p_occurred_at,updated_at=now()
   where id=p_participant_id and organisation_id=p_org_id;
  if v_referral_id is not null then
   update public.jl_trial_recruitment_referrals set status='closed',updated_at=now()
    where id=v_referral_id and org_id=p_org_id;
  end if;
 end if;
 return v_event_id;
end;
$function$;

revoke all on function public.jl_record_trial_participant_event(uuid,uuid,text,timestamptz,text,text,jsonb) from public,anon;
grant execute on function public.jl_record_trial_participant_event(uuid,uuid,text,timestamptz,text,text,jsonb) to authenticated;

comment on column public.jl_trial_participants.consent_record_reference is
 'Controlled source-system reference to the consent evidence. Never store the signed consent document or its free-text contents in this field.';
