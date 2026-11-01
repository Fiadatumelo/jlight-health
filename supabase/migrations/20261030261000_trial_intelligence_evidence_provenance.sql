create or replace function public.jl_build_trial_intelligence_checks(p_org_id uuid)
returns jsonb
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
declare
 v_participants bigint;v_enrolled bigint;
 v_overdue_visits bigint;v_visit_records bigint;v_overdue_refs jsonb;
 v_deviations bigint;v_deviation_records bigint;v_deviation_refs jsonb;
 v_missing_study bigint;v_missing_study_refs jsonb;
 v_incomplete_consent bigint;v_incomplete_consent_refs jsonb;
 v_ae_followup bigint;v_ae_records bigint;v_ae_refs jsonb;
 v_withdrawals bigint;v_withdrawal_refs jsonb;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','read') then
  raise exception 'Clinical Trials read permission required' using errcode='42501';
 end if;
 select count(*) into v_participants from public.jl_trial_participants where organisation_id=p_org_id;
 if v_participants=0 then return '[]'::jsonb; end if;

 select count(*) into v_visit_records from public.jl_trial_participant_events
 where organisation_id=p_org_id and event_type in ('visit_scheduled','visit_completed','visit_missed');
 select count(*) into v_overdue_visits
 from public.jl_trial_participant_events scheduled
 where scheduled.organisation_id=p_org_id and scheduled.event_type='visit_scheduled'
  and scheduled.occurred_at<now()
  and not exists(select 1 from public.jl_trial_participant_events completed
   where completed.organisation_id=scheduled.organisation_id
    and completed.participant_id=scheduled.participant_id
    and completed.event_type='visit_completed'
    and completed.occurred_at>=scheduled.occurred_at);
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participant_events','source_record_id',x.id::text,'event_type',x.event_type,'occurred_at',x.occurred_at) order by x.occurred_at desc),'[]'::jsonb)
 into v_overdue_refs from (
  select scheduled.id,scheduled.event_type,scheduled.occurred_at
  from public.jl_trial_participant_events scheduled
  where scheduled.organisation_id=p_org_id and scheduled.event_type='visit_scheduled'
   and scheduled.occurred_at<now()
   and not exists(select 1 from public.jl_trial_participant_events completed
    where completed.organisation_id=scheduled.organisation_id
     and completed.participant_id=scheduled.participant_id
     and completed.event_type='visit_completed'
     and completed.occurred_at>=scheduled.occurred_at)
  order by scheduled.occurred_at desc limit 20
 ) x;

 select count(*) into v_deviation_records from public.jl_trial_participant_events
 where organisation_id=p_org_id and event_type='protocol_deviation_recorded';
 v_deviations:=v_deviation_records;
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participant_events','source_record_id',x.id::text,'event_type',x.event_type,'occurred_at',x.occurred_at) order by x.occurred_at desc),'[]'::jsonb)
 into v_deviation_refs from (
  select id,event_type,occurred_at from public.jl_trial_participant_events
  where organisation_id=p_org_id and event_type='protocol_deviation_recorded'
  order by occurred_at desc limit 20
 ) x;

 select count(*) into v_missing_study
 from public.jl_trial_participants p left join public.jl_trial_studies s
  on s.id=p.study_id and s.organisation_id=p.organisation_id
 where p.organisation_id=p_org_id and s.id is null;
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participants','source_record_id',x.id::text,'event_type','study_link_missing','occurred_at',x.updated_at) order by x.updated_at desc),'[]'::jsonb)
 into v_missing_study_refs from (
  select p.id,p.updated_at from public.jl_trial_participants p
  left join public.jl_trial_studies s on s.id=p.study_id and s.organisation_id=p.organisation_id
  where p.organisation_id=p_org_id and s.id is null
  order by p.updated_at desc limit 20
 ) x;

 select count(*) into v_enrolled from public.jl_trial_participants
 where organisation_id=p_org_id and status='enrolled';
 select count(*) into v_incomplete_consent from public.jl_trial_participants
 where organisation_id=p_org_id and status='enrolled'
  and (consent_status<>'obtained' or consented_at is null
   or nullif(consent_version,'') is null
   or nullif(consent_record_reference,'') is null);
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participants','source_record_id',x.id::text,'event_type','consent_record_incomplete','occurred_at',x.updated_at) order by x.updated_at desc),'[]'::jsonb)
 into v_incomplete_consent_refs from (
  select id,updated_at from public.jl_trial_participants
  where organisation_id=p_org_id and status='enrolled'
   and (consent_status<>'obtained' or consented_at is null
    or nullif(consent_version,'') is null or nullif(consent_record_reference,'') is null)
  order by updated_at desc limit 20
 ) x;

 select count(*) into v_ae_records from public.jl_trial_participant_events
 where organisation_id=p_org_id and event_type in ('adverse_event_recorded','serious_adverse_event_recorded');
 select count(*) into v_ae_followup from public.jl_trial_participant_events
 where organisation_id=p_org_id
  and event_type in ('adverse_event_recorded','serious_adverse_event_recorded')
  and (lower(coalesce(status,'')) in ('open','pending','unresolved','follow_up_required')
   or (event_type='serious_adverse_event_recorded' and nullif(metadata->>'sae_reported_at','') is null));
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participant_events','source_record_id',x.id::text,'event_type',x.event_type,'occurred_at',x.occurred_at) order by x.occurred_at desc),'[]'::jsonb)
 into v_ae_refs from (
  select id,event_type,occurred_at from public.jl_trial_participant_events
  where organisation_id=p_org_id
   and event_type in ('adverse_event_recorded','serious_adverse_event_recorded')
   and (lower(coalesce(status,'')) in ('open','pending','unresolved','follow_up_required')
    or (event_type='serious_adverse_event_recorded' and nullif(metadata->>'sae_reported_at','') is null))
  order by occurred_at desc limit 20
 ) x;

 select count(*) into v_withdrawals from public.jl_trial_participants
 where organisation_id=p_org_id and status='withdrawn';
 select coalesce(jsonb_agg(jsonb_build_object('source_table','jl_trial_participants','source_record_id',x.id::text,'event_type','participant_withdrawn','occurred_at',x.withdrawn_at) order by x.withdrawn_at desc),'[]'::jsonb)
 into v_withdrawal_refs from (
  select id,withdrawn_at from public.jl_trial_participants
  where organisation_id=p_org_id and status='withdrawn'
  order by withdrawn_at desc limit 20
 ) x;

 return jsonb_build_array(
  jsonb_build_object('check_id','overdue_visit','rule_version','ct-ops-2026.10.1','status',case when v_visit_records=0 then 'unknown' when v_overdue_visits>0 then 'review' else 'pass' end,'severity','medium','evidence_count',v_overdue_visits,'evidence_refs',v_overdue_refs),
  jsonb_build_object('check_id','protocol_deviation','rule_version','ct-ops-2026.10.1','status',case when v_deviation_records=0 then 'unknown' when v_deviations>0 then 'review' else 'pass' end,'severity','medium','evidence_count',v_deviations,'evidence_refs',v_deviation_refs),
  jsonb_build_object('check_id','incomplete_trial_record','rule_version','ct-ops-2026.10.1','status',case when v_missing_study>0 then 'review' else 'pass' end,'severity','high','evidence_count',v_missing_study,'evidence_refs',v_missing_study_refs),
  jsonb_build_object('check_id','consent_record_incomplete','rule_version','ct-ops-2026.10.1','status',case when v_enrolled=0 then 'unknown' when v_incomplete_consent>0 then 'review' else 'pass' end,'severity','critical','evidence_count',v_incomplete_consent,'evidence_refs',v_incomplete_consent_refs),
  jsonb_build_object('check_id','adverse_event_followup','rule_version','ct-ops-2026.10.1','status',case when v_ae_records=0 then 'unknown' when v_ae_followup>0 then 'review' else 'pass' end,'severity','high','evidence_count',v_ae_followup,'evidence_refs',v_ae_refs),
  jsonb_build_object('check_id','participant_withdrawal','rule_version','ct-ops-2026.10.1','status',case when v_withdrawals>0 then 'review' else 'pass' end,'severity','low','evidence_count',v_withdrawals,'evidence_refs',v_withdrawal_refs)
 );
end;
$function$;
revoke all on function public.jl_build_trial_intelligence_checks(uuid) from public,anon;
grant execute on function public.jl_build_trial_intelligence_checks(uuid) to authenticated;
comment on function public.jl_build_trial_intelligence_checks(uuid) is
 'Server-derived de-identified Clinical Trials workflow checks with bounded source-record references, rule version and explicit unknown status when evidence is absent.';
