# JLIGHT Cross-Section Intelligence — Staging Validation

Do not apply directly to production. First verify the current Supabase schema, especially that `jl_organisations.id` is UUID.

After applying migration `202610220003_cross_section_intelligence_foundation.sql` in staging, test:
1. Two organisations cannot read or write each other's rows in every new table.
2. Users without active membership see no tenant records and cannot insert.
3. Read-only members cannot write.
4. Laboratory-only members cannot read trial participants.
5. Clinical-trial-only members cannot read routine patient records unless separately assigned that role.
6. Encounter and observation links cannot cross organisation/patient boundaries.
7. Browser clients cannot create, modify or delete membership rows.
8. Browser clients cannot update/delete review event history.
9. Findings retain provenance, rule version, and human-review status.
10. Confirm application signup and existing workflows still work with the new tables.

If any test fails, stop; do not disable RLS or broaden policies as a workaround. Commercial release also requires automated regression tests, POPIA/legal review, incident response, monitoring, tested backups and independent penetration testing.
