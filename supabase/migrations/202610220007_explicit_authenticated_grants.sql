-- Explicit least-privilege SQL grants; RLS policies remain the row-level boundary.
BEGIN;
GRANT SELECT ON public.jl_org_memberships TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.jl_patients TO authenticated;
GRANT SELECT, INSERT ON public.jl_encounters TO authenticated;
GRANT SELECT, INSERT ON public.jl_source_observations TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.jl_intelligence_findings TO authenticated;
-- Browser clients read review history but must use jl_review_finding() to append
-- events; direct inserts would allow forged audit history.
GRANT SELECT ON public.jl_finding_review_events TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.jl_finding_review_events FROM authenticated;
GRANT SELECT, INSERT, UPDATE ON public.jl_trial_studies TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.jl_trial_participants TO authenticated;

REVOKE ALL ON public.jl_org_memberships FROM anon;
REVOKE ALL ON public.jl_patients FROM anon;
REVOKE ALL ON public.jl_encounters FROM anon;
REVOKE ALL ON public.jl_source_observations FROM anon;
REVOKE ALL ON public.jl_intelligence_findings FROM anon;
REVOKE ALL ON public.jl_finding_review_events FROM anon;
REVOKE ALL ON public.jl_trial_studies FROM anon;
REVOKE ALL ON public.jl_trial_participants FROM anon;
COMMIT;
