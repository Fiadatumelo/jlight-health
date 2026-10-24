-- Run with Supabase CLI: supabase test db
BEGIN;
SELECT plan(16);

SELECT ok(
  (SELECT relrowsecurity FROM pg_class WHERE oid='public.jl_patients'::regclass),
  'existing patient table keeps RLS enabled'
);

SELECT ok(
  EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.jl_org_memberships'::regclass AND conname='jl_org_memberships_org_user_role_key'),
  'organisation membership supports separately granted roles per user'
);
SELECT ok(
  (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.jl_source_observations'::regclass),
  'observation table has RLS enabled and forced'
);
SELECT ok(
  (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.jl_intelligence_findings'::regclass),
  'findings table has RLS enabled and forced'
);
SELECT ok(
  (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.jl_trial_participants'::regclass),
  'trial participants table has RLS enabled and forced'
);
SELECT ok(
  NOT has_table_privilege('anon','public.jl_patients','SELECT'),
  'anon cannot select patient records'
);
SELECT ok(
  NOT has_table_privilege('anon','public.jl_trial_participants','SELECT'),
  'anon cannot select trial participants'
);
SELECT ok(
  NOT has_table_privilege('authenticated','public.jl_org_memberships','INSERT'),
  'authenticated clients cannot create memberships directly'
);
SELECT ok(
  NOT has_table_privilege('authenticated','public.jl_finding_review_events','INSERT'),
  'authenticated clients cannot forge review events directly'
);
SELECT ok(
  has_function_privilege('authenticated','public.jl_review_finding(uuid,text,text)','EXECUTE'),
  'authenticated users can call controlled finding-review RPC'
);
SELECT ok(
  NOT has_function_privilege('anon','public.jl_review_finding(uuid,text,text)','EXECUTE'),
  'anonymous users cannot call finding-review RPC'
);
SELECT ok(
  EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='jl_patients' AND policyname='patients_org'),
  'existing patient access policy is preserved'
);
SELECT ok(
  EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='jl_trial_participants' AND policyname='jl_trial_participants_select'),
  'trial participant access is governed by an explicit select policy'
);

SELECT ok(
  has_function_privilege('authenticated','public.jl_accept_organisation_invitations()','EXECUTE'),
  'authenticated users can accept their own confirmed invitations through the controlled RPC'
);
SELECT ok(
  NOT has_function_privilege('anon','public.jl_accept_organisation_invitations()','EXECUTE'),
  'anonymous users cannot activate invitations'
);

SELECT ok(
  EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='jl_organisation_owner_membership_seed' AND NOT tgisinternal),
  'new organisations automatically receive an owner membership'
);

SELECT * FROM finish();
ROLLBACK;
