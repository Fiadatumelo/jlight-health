-- These legacy/operational tables have no approved browser-facing access contract.
-- Keep them fail-closed until a table-specific tenant policy and product workflow are reviewed.
revoke all on table public.alerts from anon, authenticated;
revoke all on table public.audit_log from anon, authenticated;
revoke all on table public.csv_uploads from anon, authenticated;
revoke all on table public.decision_cards from anon, authenticated;
revoke all on table public.jl_samples from anon, authenticated;
revoke all on table public.profiles from anon, authenticated;
revoke all on table public.system_health_log from anon, authenticated;
