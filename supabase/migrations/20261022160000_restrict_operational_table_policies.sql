-- JLIGHT Priority 1: contain anonymous access to operational tables.
-- This migration intentionally removes broad PUBLIC policies. It does not grant
-- replacement access until an explicit operational role and access path are defined.
-- Apply only to staging first and validate integrations before any production rollout.

alter table public.alerts enable row level security;
alter table public.system_health_log enable row level security;

drop policy if exists anon_read_alerts on public.alerts;
drop policy if exists anon_write_alerts on public.alerts;

drop policy if exists allow_all_health on public.system_health_log;
drop policy if exists anon_read_health on public.system_health_log;
drop policy if exists anon_write_health on public.system_health_log;

-- No replacement client policies are added here. The current frontend does not
-- reference these tables. Service-role/server-side operations can continue under
-- the service role's intended privileges. If a user-facing feature needs either
-- table, add a narrowly scoped authenticated policy after defining its role model.
