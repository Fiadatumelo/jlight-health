begin;

-- The previous policies on these tables only required organisation membership.
-- Replace them with workspace-scoped permissions so Hospital/Laboratory/Trial
-- members cannot read or mutate Bioinformatics records by virtue of org membership.
drop policy if exists bio_acc_org on public.jl_bio_accessions;
drop policy if exists bio_runs_org on public.jl_bio_runs;
drop policy if exists bio_qc_org on public.jl_bio_qc;
drop policy if exists bio_amr_org on public.jl_bio_amr;

drop policy if exists jlight_tenant_membership_fence on public.jl_bio_accessions;
drop policy if exists jlight_tenant_membership_fence on public.jl_bio_runs;
drop policy if exists jlight_tenant_membership_fence on public.jl_bio_qc;
drop policy if exists jlight_tenant_membership_fence on public.jl_bio_amr;

create policy bio_accessions_workspace_select
on public.jl_bio_accessions
for select to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'read'))
);

create policy bio_accessions_workspace_insert
on public.jl_bio_accessions
for insert to authenticated
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_accessions_workspace_update
on public.jl_bio_accessions
for update to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
)
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_accessions_workspace_delete
on public.jl_bio_accessions
for delete to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_runs_workspace_select
on public.jl_bio_runs
for select to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'read'))
);

create policy bio_runs_workspace_insert
on public.jl_bio_runs
for insert to authenticated
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_runs_workspace_update
on public.jl_bio_runs
for update to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
)
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_runs_workspace_delete
on public.jl_bio_runs
for delete to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_qc_workspace_select
on public.jl_bio_qc
for select to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'read'))
);

create policy bio_qc_workspace_insert
on public.jl_bio_qc
for insert to authenticated
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_qc_workspace_update
on public.jl_bio_qc
for update to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
)
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_qc_workspace_delete
on public.jl_bio_qc
for delete to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_amr_workspace_select
on public.jl_bio_amr
for select to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'read'))
);

create policy bio_amr_workspace_insert
on public.jl_bio_amr
for insert to authenticated
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_amr_workspace_update
on public.jl_bio_amr
for update to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
)
with check (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

create policy bio_amr_workspace_delete
on public.jl_bio_amr
for delete to authenticated
using (
  org_id = (select private.jl_current_org_id())
  and (select public.jlight_has_domain_permission((select private.jl_current_org_id()), 'bioinformatics', 'write'))
);

commit;
