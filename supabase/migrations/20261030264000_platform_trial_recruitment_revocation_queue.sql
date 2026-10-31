create or replace function public.jl_list_active_trial_recruitment_authorisations()
returns table(
 study_id uuid,organisation_id uuid,organisation_name text,study_code text,title text,
 ethics_approval_date date,criteria_version text,authorised_at timestamptz
)
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
begin
 if auth.uid() is null or not public.jl_is_platform_super_admin() then
  raise exception 'JLIGHT Platform Administrator access required' using errcode='42501';
 end if;
 return query
 select s.id,s.organisation_id,o.name,s.study_code,s.title,
  s.ethics_approval_date,s.recruitment_criteria_version,s.recruitment_authorised_at
 from public.jl_trial_studies s join public.jl_organisations o on o.id=s.organisation_id
 where s.status='active' and s.recruitment_enabled=true
 order by s.recruitment_authorised_at desc limit 500;
end;
$function$;
revoke all on function public.jl_list_active_trial_recruitment_authorisations() from public,anon;
grant execute on function public.jl_list_active_trial_recruitment_authorisations() to authenticated;
