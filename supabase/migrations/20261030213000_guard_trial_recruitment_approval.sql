-- Prevent organisation trial members from self-approving recruitment.
-- Only the independent JLIGHT Platform Admin approval RPC may change these fields.

create or replace function private.jl_guard_trial_recruitment_authorisation()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, auth
as $function$
begin
  if (new.recruitment_enabled is distinct from old.recruitment_enabled)
     or (new.ethics_approval_reference is distinct from old.ethics_approval_reference)
     or (new.ethics_approval_date is distinct from old.ethics_approval_date)
     or (new.recruitment_criteria_version is distinct from old.recruitment_criteria_version)
     or (new.recruitment_authorised_by is distinct from old.recruitment_authorised_by)
     or (new.recruitment_authorised_at is distinct from old.recruitment_authorised_at) then
    if auth.uid() is null or not public.jl_is_platform_super_admin() then
      raise exception 'Only an independent JLIGHT Platform Administrator can authorise or change recruitment approval metadata'
        using errcode = '42501';
    end if;
  end if;
  return new;
end;
$function$;

revoke all on function private.jl_guard_trial_recruitment_authorisation() from public, anon, authenticated;

drop trigger if exists jl_trial_recruitment_authorisation_guard on public.jl_trial_studies;
create trigger jl_trial_recruitment_authorisation_guard
before update on public.jl_trial_studies
for each row execute function private.jl_guard_trial_recruitment_authorisation();

comment on function private.jl_guard_trial_recruitment_authorisation() is
  'Database-enforced guard: organisation owners and trial members cannot self-approve or alter ethics/recruitment authorisation fields.';
