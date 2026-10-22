-- Anonymous clients must not receive table-level privileges on JLIGHT domain tables.
-- Browser access is authenticated-only; RLS remains the tenant boundary.
do $$
declare t record;
begin
  for t in
    select tablename from pg_tables
    where schemaname = 'public' and tablename like 'jl\_%' escape '\'
  loop
    execute format('revoke all on table public.%I from anon', t.tablename);
  end loop;
end $$;
