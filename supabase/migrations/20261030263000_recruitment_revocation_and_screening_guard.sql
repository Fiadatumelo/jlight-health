alter table public.jl_trial_studies
 add column if not exists recruitment_revoked_by uuid references auth.users(id),
 add column if not exists recruitment_revoked_at timestamptz,
 add column if not exists recruitment_revocation_reason text;

alter table public.jl_trial_study_events drop constraint if exists jl_trial_study_events_event_type_check;
alter table public.jl_trial_study_events add constraint jl_trial_study_events_event_type_check
 check(event_type in ('study_created','study_activated','legacy_protocol_linked','recruitment_authorised','recruitment_revoked'));

create or replace function private.jl_guard_trial_recruitment_authorisation()
returns trigger language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
begin
 if (new.recruitment_enabled is distinct from old.recruitment_enabled)
  or (new.ethics_approval_reference is distinct from old.ethics_approval_reference)
  or (new.ethics_approval_date is distinct from old.ethics_approval_date)
  or (new.recruitment_criteria_version is distinct from old.recruitment_criteria_version)
  or (new.recruitment_authorised_by is distinct from old.recruitment_authorised_by)
  or (new.recruitment_authorised_at is distinct from old.recruitment_authorised_at)
  or (new.recruitment_revoked_by is distinct from old.recruitment_revoked_by)
  or (new.recruitment_revoked_at is distinct from old.recruitment_revoked_at)
  or (new.recruitment_revocation_reason is distinct from old.recruitment_revocation_reason) then
  if auth.uid() is null or not public.jl_is_platform_super_admin() then
   raise exception 'Only an independent JLIGHT Platform Administrator can authorise or revoke recruitment'
    using errcode='42501';
  end if;
 end if;
 return new;
end;
$function$;
revoke all on function private.jl_guard_trial_recruitment_authorisation() from public,anon,authenticated;

create or replace function public.jl_authorise_trial_recruitment(
 p_study_id uuid,p_ethics_approval_reference text,p_ethics_approval_date date,p_criteria_version text
) returns void
language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_org_id uuid;
begin
 if auth.uid() is null or not public.jl_is_platform_super_admin() then
  raise exception 'Independent JLIGHT Platform Administrator approval is required' using errcode='42501';
 end if;
 if nullif(btrim(p_ethics_approval_reference),'') is null
  or length(p_ethics_approval_reference)>200
  or p_ethics_approval_date is null or p_ethics_approval_date>current_date
  or nullif(btrim(p_criteria_version),'') is null or length(p_criteria_version)>80 then
  raise exception 'Valid ethics approval reference, date and recruitment criteria version are required' using errcode='22023';
 end if;
 select organisation_id into v_org_id from public.jl_trial_studies where id=p_study_id for update;
 if v_org_id is null then raise exception 'Study not found' using errcode='P0002'; end if;
 update public.jl_trial_studies set recruitment_enabled=true,
  ethics_approval_reference=btrim(p_ethics_approval_reference),
  ethics_approval_date=p_ethics_approval_date,
  recruitment_criteria_version=btrim(p_criteria_version),
  recruitment_authorised_by=auth.uid(),recruitment_authorised_at=now(),
  recruitment_revoked_by=null,recruitment_revoked_at=null,recruitment_revocation_reason=null,
  updated_at=now()
 where id=p_study_id;
 insert into public.jl_trial_study_events(organisation_id,study_id,event_type,actor_id,metadata)
 values(v_org_id,p_study_id,'recruitment_authorised',auth.uid(),
  jsonb_build_object('criteria_version',btrim(p_criteria_version),'ethics_approval_date',p_ethics_approval_date));
end;
$function$;
revoke all on function public.jl_authorise_trial_recruitment(uuid,text,date,text) from public,anon;
grant execute on function public.jl_authorise_trial_recruitment(uuid,text,date,text) to authenticated;

create or replace function public.jl_revoke_trial_recruitment(p_study_id uuid,p_reason text)
returns void language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_org_id uuid;v_enabled boolean;
begin
 if auth.uid() is null or not public.jl_is_platform_super_admin() then
  raise exception 'Independent JLIGHT Platform Administrator approval is required' using errcode='42501';
 end if;
 if nullif(btrim(p_reason),'') is null or length(p_reason)>500 then
  raise exception 'A concise revocation reason is required' using errcode='22023';
 end if;
 select organisation_id,recruitment_enabled into v_org_id,v_enabled
 from public.jl_trial_studies where id=p_study_id for update;
 if v_org_id is null then raise exception 'Study not found' using errcode='P0002'; end if;
 if v_enabled is distinct from true then raise exception 'Recruitment is not currently authorised' using errcode='22023'; end if;
 update public.jl_trial_studies set recruitment_enabled=false,
  recruitment_revoked_by=auth.uid(),recruitment_revoked_at=now(),
  recruitment_revocation_reason=btrim(p_reason),updated_at=now()
 where id=p_study_id;
 insert into public.jl_trial_study_events(organisation_id,study_id,event_type,actor_id,metadata)
 values(v_org_id,p_study_id,'recruitment_revoked',auth.uid(),jsonb_build_object('reason',btrim(p_reason)));
end;
$function$;
revoke all on function public.jl_revoke_trial_recruitment(uuid,text) from public,anon;
grant execute on function public.jl_revoke_trial_recruitment(uuid,text) to authenticated;

create or replace function public.jl_create_trial_participant_from_referral(
 p_org_id uuid,p_referral_id uuid,p_participant_code text,p_site_code text default null
) returns uuid
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_study_id uuid;v_status text;v_participant_id uuid;
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
  where s.id=v_study_id and s.organisation_id=p_org_id and s.status='active'
   and s.recruitment_enabled=true and s.ethics_approval_reference is not null
   and s.ethics_approval_date is not null and s.ethics_approval_date<=current_date
   and s.recruitment_criteria_version is not null) then
  raise exception 'Study recruitment approval is not current; screening cannot proceed' using errcode='42501';
 end if;
 insert into public.jl_trial_participants
  (organisation_id,study_id,participant_code,status,created_by,recruitment_referral_id,site_code,consent_status)
 values(p_org_id,v_study_id,btrim(p_participant_code),'screening',auth.uid(),p_referral_id,
  nullif(btrim(p_site_code),''),'not_obtained')
 returning id into v_participant_id;
 update public.jl_trial_recruitment_referrals set status='screening',
  received_by=coalesce(received_by,auth.uid()),received_at=coalesce(received_at,now()),updated_at=now()
 where id=p_referral_id and org_id=p_org_id;
 update private.jl_trial_recruitment_identity_links set linked_participant_id=v_participant_id
 where referral_id=p_referral_id and org_id=p_org_id and link_status='active';
 insert into public.jl_trial_recruitment_events
  (org_id,referral_id,event_type,from_status,to_status,actor_id,rationale_code)
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
