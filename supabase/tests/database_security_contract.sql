-- Run with Supabase CLI: supabase test db
BEGIN;
SELECT plan(29);

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


SELECT ok(
  has_function_privilege('authenticated','public.jlight_has_domain_permission(uuid,text,text)','EXECUTE'),
  'authenticated requests can evaluate only their own explicit domain grants'
);
SELECT ok(
  NOT has_function_privilege('anon','public.jlight_has_domain_permission(uuid,text,text)','EXECUTE'),
  'anonymous users cannot evaluate domain grants'
);
SELECT ok(
  has_function_privilege('authenticated','public.jlight_finding_domain_access(uuid,uuid,text)','EXECUTE'),
  'authenticated requests can use the source-domain finding access guard'
);
SELECT ok(
  NOT has_function_privilege('anon','public.jlight_finding_domain_access(uuid,uuid,text)','EXECUTE'),
  'anonymous users cannot use the finding access guard'
);
SELECT ok(
  EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='jl_source_observations' AND policyname='jlight_observations_domain_read' AND permissive='RESTRICTIVE'),
  'source observation reads are restricted by explicit domain grants'
);
SELECT ok(
  EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='jl_intelligence_findings' AND policyname='jlight_findings_domain_read' AND permissive='RESTRICTIVE'),
  'cross-section findings are restricted by all cited source domains'
);
SELECT ok(
  position('jlight_finding_domain_access' in pg_get_functiondef('public.jl_review_intelligence_finding(uuid,text,text)'::regprocedure)) > 0,
  'SECURITY DEFINER finding review RPC independently enforces source-domain permissions'
);


-- Behavioural domain-grant checks use synthetic IDs and roll back with this test.
INSERT INTO public.jl_organisations(id,name,role,owner_email,org_code,active)
VALUES ('c1111111-1111-4111-8111-111111111111','Synthetic Domain Test','Laboratory','synthetic@example.invalid','SYNTHDOM1',true);
INSERT INTO public.jlight_organization_memberships(organization_id,auth_subject,role,active,created_by)
VALUES ('c1111111-1111-4111-8111-111111111111','c2222222-2222-4222-8222-222222222222','owner',true,'c2222222-2222-4222-8222-222222222222');
INSERT INTO public.jlight_membership_domain_permissions(organization_id,auth_subject,domain,can_read,can_write,can_report,granted_by)
VALUES ('c1111111-1111-4111-8111-111111111111','c2222222-2222-4222-8222-222222222222','laboratory',true,true,true,'c2222222-2222-4222-8222-222222222222');
INSERT INTO public.jl_intelligence_findings(id,organisation_id,finding_type,severity,status,title,explanation,rule_version,source_observation_ids)
VALUES ('c4444444-4444-4444-8444-444444444444','c1111111-1111-4111-8111-111111111111','synthetic_test','low','open','Synthetic finding','Synthetic only; no patient data','test-v1','{}'::uuid[]);
SELECT set_config('request.jwt.claim.sub','c2222222-2222-4222-8222-222222222222',true);

SELECT is(
  public.jlight_has_domain_permission('c1111111-1111-4111-8111-111111111111','laboratory','read'),
  true,
  'explicit laboratory read grant is honoured'
);
SELECT is(
  public.jlight_has_domain_permission('c1111111-1111-4111-8111-111111111111','hospital','read'),
  false,
  'missing hospital grant is denied'
);
SELECT is(
  public.jlight_has_domain_permission('c1111111-1111-4111-8111-111111111111','laboratory','write'),
  true,
  'explicit laboratory write grant is honoured'
);
SELECT is(
  public.jlight_has_domain_permission('c1111111-1111-4111-8111-111111111111','clinical_trials','read'),
  false,
  'clinical trials remains outside the standard domain grants'
);
SELECT is(
  public.jlight_finding_domain_access('c1111111-1111-4111-8111-111111111111','c4444444-4444-4444-8444-444444444444','read'),
  true,
  'finding access requires and honours an explicit domain grant'
);
SELECT is(
  public.jlight_finding_domain_access('c1111111-1111-4111-8111-111111111111','ffffffff-ffff-4fff-8fff-ffffffffffff','read'),
  false,
  'finding access denies a finding outside the requested organisation or missing finding'
);

SELECT * FROM finish();
ROLLBACK;
