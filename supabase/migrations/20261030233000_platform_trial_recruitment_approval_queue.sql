create or replace function public.jl_list_trial_recruitment_approval_queue()
returns table(
 study_id uuid,organisation_id uuid,organisation_name text,
 study_code text,title text,status text,legacy_protocol_id uuid,created_at timestamptz
)
language plpgsql stable security definer
set search_path=pg_catalog,public,auth
as $function$
begin
 if auth.uid() is null or not public.jl_is_platform_super_admin() then
  raise exception 'JLIGHT Platform Administrator access required' using errcode='42501';
 end if;
 return query
 select s.id,s.organisation_id,o.name,s.study_code,s.title,s.status,s.legacy_protocol_id,s.created_at
 from public.jl_trial_studies s
 join public.jl_organisations o on o.id=s.organisation_id
 where s.status='active' and s.recruitment_enabled=false
 order by s.created_at asc
 limit 500;
end;
$function$;
revoke all on function public.jl_list_trial_recruitment_approval_queue() from public,anon;
grant execute on function public.jl_list_trial_recruitment_approval_queue() to authenticated;
comment on function public.jl_list_trial_recruitment_approval_queue() is
 'Platform-admin-only queue of active studies awaiting independent ethics and recruitment approval.';
