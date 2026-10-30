alter table public.jl_trial_study_events drop constraint if exists jl_trial_study_events_event_type_check;
alter table public.jl_trial_study_events add constraint jl_trial_study_events_event_type_check
 check(event_type in ('study_created','study_activated','legacy_protocol_linked'));

create or replace function public.jl_create_trial_study(p_org_id uuid,p_study_code text,p_title text)
returns uuid language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_id uuid;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
  raise exception 'Clinical Trials write permission required' using errcode='42501';
 end if;
 if nullif(btrim(p_study_code),'') is null or length(p_study_code)>80
  or nullif(btrim(p_title),'') is null or length(p_title)>240 then
  raise exception 'Study code and title are required and must be within their length limits' using errcode='22023';
 end if;
 insert into public.jl_trial_studies(organisation_id,study_code,title,status,created_by)
 values(p_org_id,btrim(p_study_code),btrim(p_title),'planning',auth.uid())
 returning id into v_id;
 insert into public.jl_trial_study_events(organisation_id,study_id,event_type,actor_id,metadata)
 values(p_org_id,v_id,'study_created',auth.uid(),'{}'::jsonb);
 return v_id;
end;
$function$;

create or replace function public.jl_activate_trial_study(p_org_id uuid,p_study_id uuid)
returns void language plpgsql security definer
set search_path=pg_catalog,public,auth
as $function$
declare v_changed boolean:=false;
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'clinical_trials','write') then
  raise exception 'Clinical Trials write permission required' using errcode='42501';
 end if;
 update public.jl_trial_studies set status='active',updated_at=now()
 where id=p_study_id and organisation_id=p_org_id and status in ('planning','paused');
 v_changed:=found;
 if v_changed then
  insert into public.jl_trial_study_events(organisation_id,study_id,event_type,actor_id,metadata)
  values(p_org_id,p_study_id,'study_activated',auth.uid(),'{}'::jsonb);
 elsif not exists(select 1 from public.jl_trial_studies where id=p_study_id and organisation_id=p_org_id and status='active') then
  raise exception 'Study not found or cannot be activated from its current state' using errcode='P0002';
 end if;
end;
$function$;

revoke all on function public.jl_create_trial_study(uuid,text,text) from public,anon;
grant execute on function public.jl_create_trial_study(uuid,text,text) to authenticated;
revoke all on function public.jl_activate_trial_study(uuid,uuid) from public,anon;
grant execute on function public.jl_activate_trial_study(uuid,uuid) to authenticated;
