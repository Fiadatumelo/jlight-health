-- Restore the global UNIQUE(jl_id) contract on jl_entries for staging.
-- The repo contract is documented in 20261022130000_jl_entries_domain_persistence.sql
-- ("Preserve the existing global UNIQUE(jl_id) contract for compatibility") and is
-- asserted by supabase/tests/priority1_catalog_assertions.sql. Every other writer
-- target table (jl_audit, jl_cards, jl_requests, jl_samples) already carries this
-- constraint; jl_entries alone was found without it on the staging project, which
-- breaks PostgREST upserts declared with ON CONFLICT (jl_id).
-- Additive and idempotent: fails loudly if duplicate jl_id rows exist, because
-- application assumptions depend on stable, unique entry identifiers.

do $$
declare
  v_duplicates integer;
begin
  if exists (
    select 1 from pg_constraint
    where conrelid = 'public.jl_entries'::regclass
      and conname = 'jl_entries_jl_id_key'
  ) then
    raise notice 'jl_entries_jl_id_key already present; nothing to do';
    return;
  end if;

  select count(*) into v_duplicates
  from (
    select jl_id from public.jl_entries
    where jl_id is not null
    group by jl_id having count(*) > 1
  ) d;
  if v_duplicates > 0 then
    raise exception 'Cannot restore UNIQUE(jl_id): % duplicate jl_id value(s) exist in jl_entries; reconcile rows first', v_duplicates;
  end if;

  alter table public.jl_entries
    add constraint jl_entries_jl_id_key unique (jl_id);
end
$$;
