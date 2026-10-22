-- Correct the blanket least-privilege grant so it does not undo column-level protection.
revoke update on table public.jl_user_profiles from authenticated;
grant update (full_name, employee_id, job_title, qualification, domains, last_seen)
  on table public.jl_user_profiles to authenticated;

-- Organisation membership and routing identity are managed by controlled server-side flows.
-- No browser workflow currently needs direct organisation-row updates.
revoke update on table public.jl_organisations from authenticated;
