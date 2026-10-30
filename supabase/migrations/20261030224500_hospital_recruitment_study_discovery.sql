-- Expose only currently approved, recruitable study metadata to Hospital writers.
create or replace function public.jl_list_recruitable_trial_studies(p_org_id uuid)
returns table(study_id uuid,study_code text,title text,status text,site_codes text[],criteria_version text)
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
begin
 if auth.uid() is null or not public.jlight_has_domain_permission(p_org_id,'hospital','write') then
  raise exception 'Hospital write permission required' using errcode='42501';
 end if;
 if not exists(select 1 from public.jl_organisation_workspaces w
   where w.org_id=p_org_id and w.workspace_key='clinical_trials' and w.status='active') then
  raise exception 'Clinical Trials pathway is not active for this organisation' using errcode='42501';
 end if;
 return query
 select s.id,s.study_code,s.title,s.status,s.site_codes,s.recruitment_criteria_version
 from public.jl_trial_studies s
 where s.organisation_id=p_org_id and s.status='active' and s.recruitment_enabled=true
   and s.ethics_approval_reference is not null
   and s.ethics_approval_date is not null and s.ethics_approval_date<=current_date
 order by s.study_code;
end;
$function$;
revoke all on function public.jl_list_recruitable_trial_studies(uuid) from public,anon;
grant execute on function public.jl_list_recruitable_trial_studies(uuid) to authenticated;
comment on function public.jl_list_recruitable_trial_studies(uuid) is
 'Returns minimum-necessary metadata for currently approved Clinical Trials studies to authorised Hospital writers. Never returns patient or participant identities or ethics reference text.';
