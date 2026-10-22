# JLIGHT Cross-Section Intelligence — Staging Validation

Do not apply directly to production. First verify the current Supabase schema. JLIGHT already has `public.jl_patients` with `org_id` (not `organisation_id`); the integration must reuse that table and preserve its existing `patients_org` policy.

Apply migrations `202610220003` through `202610220011` in numeric order in a disposable staging project, after verifying the existing schema. Then run `supabase test db` to execute `supabase/tests/database_security_contract.sql` and perform the manual checks below.
1. Two organisations cannot read or write each other's rows in every new table.
2. Users without active membership see no tenant records and cannot insert.
3. Read-only members cannot write.
4. Laboratory-only members cannot read trial participants.
5. Clinical-trial-only members cannot read routine patient records unless separately assigned that role.
6. Encounter and observation links cannot cross organisation/patient boundaries.
7. Browser clients cannot create, modify or delete membership rows.
8. Authenticated browser clients cannot insert, update or delete review events directly; review writes go through `jl_review_finding`.
9. Findings retain provenance, rule version, and human-review status.
9. Reviewers can only change finding review state through `jl_review_finding`; they cannot directly edit finding content.
10. The review RPC creates an event with the authenticated actor and rejects unauthorised users.
11. Confirm application signup and existing workflows still work with the new tables.

If any test fails, stop; do not disable RLS or broaden policies as a workaround. Commercial release also requires automated regression tests, POPIA/legal review, incident response, monitoring, tested backups and independent penetration testing.

12. Confirm explicit authenticated grants work as intended and the anon role has no access to tenant tables.
13. Test the invitation Edge Function against staging secrets, exact allowed origins, owner/admin role rules, duplicate memberships and invite failure recovery.
14. Confirm migrations 003–011 apply in order on a clean staging clone matching the live schema. Migration 003 must not create, replace, force RLS on, or add conflicting policies to the existing `jl_patients` table. Confirm existing signup, workspace, patient, card and offline-sync flows remain functional.
15. Verify the Edge Function invite acceptance route and ensure membership remains inactive until the invited user has authenticated and confirmed their email.
16. Confirm `jl_accept_organisation_invitations()` only activates invitations belonging to the current authenticated, email-confirmed user.
18. Create an organisation through the existing `jl_create_organisation` RPC and verify the creator receives an active `owner` membership.
18. Verify that one user can hold multiple explicitly granted roles in the same organisation, that module switching checks active database memberships, and that clinical-trial access requires the explicit `clinical_trial` role.
