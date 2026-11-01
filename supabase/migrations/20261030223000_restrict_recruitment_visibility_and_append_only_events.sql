-- Correct referral visibility to the referring Hospital member, and make event history append-only.
drop policy if exists jl_trial_recruitment_referrals_read on public.jl_trial_recruitment_referrals;
create policy jl_trial_recruitment_referrals_read
on public.jl_trial_recruitment_referrals for select to authenticated
using (
  (referred_by=(select auth.uid())
    and (select public.jlight_has_domain_permission(org_id,'hospital','write')))
  or (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
);

drop policy if exists jl_trial_recruitment_events_read on public.jl_trial_recruitment_events;
create policy jl_trial_recruitment_events_read
on public.jl_trial_recruitment_events for select to authenticated
using (
  exists (
    select 1 from public.jl_trial_recruitment_referrals r
    where r.id=referral_id and r.org_id=org_id
      and (
        (r.referred_by=(select auth.uid())
          and (select public.jlight_has_domain_permission(org_id,'hospital','write')))
        or (select public.jlight_has_domain_permission(org_id,'clinical_trials','read'))
      )
  )
);

revoke insert,update,delete,truncate,references,trigger on public.jl_trial_recruitment_events from anon,authenticated;
revoke insert,update,delete,truncate,references,trigger on public.jl_trial_participant_events from anon,authenticated;
grant select on public.jl_trial_recruitment_events,public.jl_trial_participant_events to authenticated;

create or replace function private.jl_reject_trial_event_mutation()
returns trigger language plpgsql
set search_path=pg_catalog
as $function$
begin
 raise exception 'Clinical Trials event history is append-only; record a correcting event instead'
  using errcode='55000';
end;
$function$;
revoke all on function private.jl_reject_trial_event_mutation() from public,anon,authenticated;

drop trigger if exists jl_trial_recruitment_events_append_only on public.jl_trial_recruitment_events;
create trigger jl_trial_recruitment_events_append_only
before update or delete on public.jl_trial_recruitment_events
for each row execute function private.jl_reject_trial_event_mutation();

drop trigger if exists jl_trial_participant_events_append_only on public.jl_trial_participant_events;
create trigger jl_trial_participant_events_append_only
before update or delete on public.jl_trial_participant_events
for each row execute function private.jl_reject_trial_event_mutation();

comment on table public.jl_trial_recruitment_events is
 'Append-only audit history for governed recruitment hand-offs. Hospital referrers see only their own referral history; authorised Clinical Trials members see study hand-offs.';
comment on table public.jl_trial_participant_events is
 'Append-only Clinical Trial Participant Timeline. Corrections are recorded as new events, not destructive edits.';
