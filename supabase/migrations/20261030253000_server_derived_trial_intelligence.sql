-- Server-derived, de-identified Clinical Trials intelligence checks.
-- The client cannot submit or spoof evidence counts.
create or replace function public.jl_build_trial_intelligence_checks(p_org_id uuid)
returns jsonb
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
declare
 v_overdue_visits bigint;
 v_deviations bigint;
 v_missing_study bigint;
 v_incomplete_consent bigint;
 v_ae_followup bigint;
 v_withdrawals bigint;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','read') then
  raise exception 'Clinical Trials read permission required' using errcode='42501';
 end if;

 select count(*) into v_overdue_visits
 from public.jl_trial_participant_events scheduled
 where scheduled.organisation_id=p_org_id
  and scheduled.event_type='visit_scheduled'
  and scheduled.occurred_at<now()
  and not exists(
   select 1 from public.jl_trial_participant_events completed
   where completed.organisation_id=scheduled.organisation_id
    and completed.participant_id=scheduled.participant_id
    and completed.event_type='visit_completed'
    and completed.occurred_at>=scheduled.occurred_at
  );

 select count(*) into v_deviations
 from public.jl_trial_participant_events
 where organisation_id=p_org_id and event_type='protocol_deviation_recorded';

 select count(*) into v_missing_study
 from public.jl_trial_participants p
 left join public.jl_trial_studies s
  on s.id=p.study_id and s.organisation_id=p.organisation_id
 where p.organisation_id=p_org_id and s.id is null;

 select count(*) into v_incomplete_consent
 from public.jl_trial_participants
 where organisation_id=p_org_id and status='enrolled'
  and (consent_status<>'obtained' or consented_at is null
   or nullif(consent_version,'') is null
   or nullif(consent_record_reference,'') is null);

 select count(*) into v_ae_followup
 from public.jl_trial_participant_events
 where organisation_id=p_org_id
  and event_type in ('adverse_event_recorded','serious_adverse_event_recorded')
  and (
   lower(coalesce(status,'')) in ('open','pending','unresolved','follow_up_required')
   or (event_type='serious_adverse_event_recorded'
    and nullif(metadata->>'sae_reported_at','') is null)
  );

 select count(*) into v_withdrawals
 from public.jl_trial_participants
 where organisation_id=p_org_id and status='withdrawn';

 return jsonb_build_array(
  jsonb_build_object('check_id','overdue_visit','status',case when v_overdue_visits>0 then 'review' else 'pass' end,'severity','medium','evidence_count',v_overdue_visits),
  jsonb_build_object('check_id','protocol_deviation','status',case when v_deviations>0 then 'review' else 'pass' end,'severity','medium','evidence_count',v_deviations),
  jsonb_build_object('check_id','incomplete_trial_record','status',case when v_missing_study>0 then 'review' else 'pass' end,'severity','high','evidence_count',v_missing_study),
  jsonb_build_object('check_id','consent_record_incomplete','status',case when v_incomplete_consent>0 then 'review' else 'pass' end,'severity','critical','evidence_count',v_incomplete_consent),
  jsonb_build_object('check_id','adverse_event_followup','status',case when v_ae_followup>0 then 'review' else 'pass' end,'severity','high','evidence_count',v_ae_followup),
  jsonb_build_object('check_id','participant_withdrawal','status',case when v_withdrawals>0 then 'review' else 'pass' end,'severity','low','evidence_count',v_withdrawals)
 );
end;
$function$;
revoke all on function public.jl_build_trial_intelligence_checks(uuid) from public,anon;
grant execute on function public.jl_build_trial_intelligence_checks(uuid) to authenticated;
comment on function public.jl_build_trial_intelligence_checks(uuid) is
 'Calculates de-identified Clinical Trials workflow signals server-side from canonical study participant and timeline tables. Client-provided counts are never trusted.';
