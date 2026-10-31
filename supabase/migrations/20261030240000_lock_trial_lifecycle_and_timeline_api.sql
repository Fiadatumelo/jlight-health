-- Lock canonical participant lifecycle writes behind audited SECURITY DEFINER operations.
revoke insert,update,delete,truncate,references,trigger on public.jl_trial_participants from anon,authenticated;
drop policy if exists jl_trial_participants_insert on public.jl_trial_participants;
drop policy if exists jl_trial_participants_update on public.jl_trial_participants;

-- Fix explicit tenant correlation in the recruitment-event visibility policy.
drop policy if exists jl_trial_recruitment_events_read on public.jl_trial_recruitment_events;
create policy jl_trial_recruitment_events_read
on public.jl_trial_recruitment_events for select to authenticated
using (
  exists (
    select 1 from public.jl_trial_recruitment_referrals r
    where r.id=jl_trial_recruitment_events.referral_id
      and r.org_id=jl_trial_recruitment_events.org_id
      and (
        (r.referred_by=(select auth.uid())
          and (select public.jlight_has_domain_permission(r.org_id,'hospital','write')))
        or (select public.jlight_has_domain_permission(r.org_id,'clinical_trials','read'))
      )
  )
);

-- Public, permission-checked wrapper returns only the de-identified trial timeline.
create or replace function public.jl_list_trial_participant_timeline(
 p_org_id uuid,p_participant_id uuid,p_limit integer default 250
) returns table(
 event_id text,event_type text,occurred_at timestamptz,status text,
 summary text,source_table text,source_record_id text,metadata jsonb
)
language sql stable security definer
set search_path=pg_catalog,public,private,auth
as $function$
 select * from private.jl_list_trial_participant_timeline(p_org_id,p_participant_id,p_limit);
$function$;
revoke all on function public.jl_list_trial_participant_timeline(uuid,uuid,integer) from public,anon;
grant execute on function public.jl_list_trial_participant_timeline(uuid,uuid,integer) to authenticated;

-- Only explicit, manually reviewed or independently approved migrations may link
-- historical participant identities to the new canonical study-scoped identity.
create or replace function private.jl_verify_legacy_trial_participant_link(
 p_org_id uuid,p_trial_participant_id uuid,p_legacy_participant_id uuid,p_method text
) returns void
language plpgsql security definer
set search_path=pg_catalog,public,private,auth
as $function$
declare v_study uuid;v_protocol uuid;v_legacy_protocol uuid;
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
 select lp.protocol_id into v_legacy_protocol from public.jl_participants lp
 where lp.id=p_legacy_participant_id and lp.org_id=p_org_id;
 if v_study is null or v_protocol is null or v_legacy_protocol is distinct from v_protocol then
  raise exception 'Legacy participant protocol is not explicitly mapped to this study' using errcode='42501';
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

create or replace function public.jl_verify_legacy_trial_participant_link(
 p_org_id uuid,p_trial_participant_id uuid,p_legacy_participant_id uuid,p_method text
) returns void
language sql security definer
set search_path=pg_catalog,public,private,auth
as $function$
 select private.jl_verify_legacy_trial_participant_link(p_org_id,p_trial_participant_id,p_legacy_participant_id,p_method);
$function$;
revoke all on function public.jl_verify_legacy_trial_participant_link(uuid,uuid,uuid,text) from public,anon;
grant execute on function public.jl_verify_legacy_trial_participant_link(uuid,uuid,uuid,text) to authenticated;

comment on table public.jl_trial_participants is
 'Canonical study-scoped participant records. Direct client writes are revoked; creation and lifecycle changes occur through validated, audited database functions.';
comment on function public.jl_list_trial_participant_timeline(uuid,uuid,integer) is
 'Returns a bounded, de-identified timeline combining canonical trial events with manually verified legacy event history.';
