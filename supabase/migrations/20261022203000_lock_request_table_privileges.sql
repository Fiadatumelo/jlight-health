-- Ensure browser roles have no table-level privileges beyond the explicitly supported request API.
revoke all on table public.jl_requests from anon;
revoke all on table public.jl_requests from authenticated;
grant select, insert, update on table public.jl_requests to authenticated;

-- The routing trigger is a browser-facing security boundary; only the table owner should replace it.
revoke all on function public.jl_guard_request_route() from public, anon, authenticated;
