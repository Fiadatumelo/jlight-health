create or replace function private.jl_verify_legacy_trial_participant_link(
 p_org_id uuid,p_trial_participant_id uuid,p_legacy_participant_id uuid,p_method text
) returns void
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare
 v_study uuid;v_protocol uuid;v_legacy_protocol uuid;
 v_linked_hospital_patient uuid;v_legacy_hospital_patient uuid;
begin
 if auth.uid() is null then raise exception 'Authentication required' using errcode='42501'; end if;
 if p_method='approved_migration' then
  if not public.jl_is_platform_super_admin() then
   raise exception 'Approved migration linking requires JLIGHT Platform Administrator approval' using errcode='42501';
  end if;
 elsif p_method='manual_source_record_review' then
  if not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
   raise exception 'Clinical Trials write permission required' using errcode='42501';
  end if;
 else
  raise exception 'A governed legacy-link verification method is required' using errcode='22023';
 end if;
 select tp.study_id,s.legacy_protocol_id into v_study,v_protocol
 from public.jl_trial_participants tp
 join public.jl_trial_studies s on s.id=tp.study_id and s.organisation_id=tp.organisation_id
 where tp.id=p_trial_participant_id and tp.organisation_id=p_org_id;
 select lp.protocol_id,lp.patient_id into v_legacy_protocol,v_legacy_hospital_patient
 from public.jl_participants lp where lp.id=p_legacy_participant_id and lp.org_id=p_org_id;
 if v_study is null or v_protocol is null or v_legacy_protocol is distinct from v_protocol then
  raise exception 'Legacy participant protocol is not explicitly mapped to this study' using errcode='42501';
 end if;
 select l.hospital_patient_id into v_linked_hospital_patient
 from private.jl_trial_recruitment_identity_links l
 where l.linked_participant_id=p_trial_participant_id and l.org_id=p_org_id and l.link_status='active';
 if v_linked_hospital_patient is not null
   and v_legacy_hospital_patient is distinct from v_linked_hospital_patient then
  raise exception 'Legacy participant identity does not match the verified Hospital recruitment identity' using errcode='42501';
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
