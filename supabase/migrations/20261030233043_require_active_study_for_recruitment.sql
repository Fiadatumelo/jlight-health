-- Clinical Trials recruitment can only be authorised for an active study
-- within an organisation that has an active Clinical Trials entitlement.

CREATE OR REPLACE FUNCTION public.jl_authorise_trial_recruitment(
  p_study_id uuid,
  p_ethics_approval_reference text,
  p_ethics_approval_date date,
  p_criteria_version text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'auth'
AS $function$
DECLARE
  v_org_id uuid;
  v_created_by uuid;
  v_study_status text;
BEGIN
  IF auth.uid() IS NULL OR NOT public.jl_is_platform_super_admin() THEN
    RAISE EXCEPTION 'Independent JLIGHT Platform Administrator approval is required'
      USING ERRCODE='42501';
  END IF;
  IF nullif(btrim(p_ethics_approval_reference),'') IS NULL
    OR length(p_ethics_approval_reference)>200
    OR p_ethics_approval_date IS NULL OR p_ethics_approval_date>current_date
    OR nullif(btrim(p_criteria_version),'') IS NULL OR length(p_criteria_version)>80 THEN
    RAISE EXCEPTION 'Valid ethics approval reference, date and recruitment criteria version are required'
      USING ERRCODE='22023';
  END IF;

  SELECT organisation_id,created_by,status
    INTO v_org_id,v_created_by,v_study_status
  FROM public.jl_trial_studies
  WHERE id=p_study_id
  FOR UPDATE;
  IF v_org_id IS NULL THEN
    RAISE EXCEPTION 'Study not found' USING ERRCODE='P0002';
  END IF;
  IF v_study_status IS DISTINCT FROM 'active' THEN
    RAISE EXCEPTION 'Recruitment can only be authorised for an active Clinical Trials study'
      USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.jl_organisation_workspaces w
    WHERE w.org_id=v_org_id AND w.workspace_key='clinical_trials' AND w.status='active'
  ) THEN
    RAISE EXCEPTION 'The organisation does not have an active Clinical Trials entitlement'
      USING ERRCODE='42501';
  END IF;
  IF v_created_by=auth.uid()
    OR EXISTS (
      SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id=v_org_id AND m.auth_subject=auth.uid() AND m.active=true
    )
    OR EXISTS (
      SELECT 1 FROM public.jl_org_memberships m
      WHERE m.organisation_id=v_org_id AND m.user_id=auth.uid() AND m.status='active'
    ) THEN
    RAISE EXCEPTION 'A platform administrator cannot authorise recruitment for a study they created or an organisation where they hold active membership'
      USING ERRCODE='42501';
  END IF;

  UPDATE public.jl_trial_studies
  SET recruitment_enabled=true,
      ethics_approval_reference=btrim(p_ethics_approval_reference),
      ethics_approval_date=p_ethics_approval_date,
      recruitment_criteria_version=btrim(p_criteria_version),
      recruitment_authorised_by=auth.uid(),
      recruitment_authorised_at=now(),
      recruitment_revoked_by=NULL,
      recruitment_revoked_at=NULL,
      recruitment_revocation_reason=NULL,
      updated_at=now()
  WHERE id=p_study_id AND organisation_id=v_org_id;

  INSERT INTO public.jl_trial_study_events
    (organisation_id,study_id,event_type,actor_id,metadata)
  VALUES
    (v_org_id,p_study_id,'recruitment_authorised',auth.uid(),
     jsonb_build_object('criteria_version',btrim(p_criteria_version),
                        'ethics_approval_date',p_ethics_approval_date));
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_create_trial_recruitment_referral(
  p_org_id uuid,
  p_study_id uuid,
  p_hospital_patient_id uuid,
  p_referral_code text,
  p_candidate_summary jsonb,
  p_criteria_version text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'private', 'auth'
AS $function$
DECLARE
  v_referral_id uuid;
  v_patient_org uuid;
  v_study_org uuid;
  v_study_status text;
  v_recruitment_enabled boolean;
  v_criteria_version text;
  v_ethics_reference text;
  v_ethics_date date;
  v_key text;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501';
  END IF;
  IF NOT public.jlight_has_domain_permission(p_org_id,'hospital','write') THEN
    RAISE EXCEPTION 'Hospital write permission required' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.jl_organisation_workspaces w
    WHERE w.org_id=p_org_id AND w.workspace_key='clinical_trials' AND w.status='active'
  ) THEN
    RAISE EXCEPTION 'Clinical Trials pathway is not active for this organisation' USING ERRCODE='42501';
  END IF;
  IF nullif(btrim(p_referral_code),'') IS NULL OR length(p_referral_code)>80
    OR jsonb_typeof(coalesce(p_candidate_summary,'{}'::jsonb))<>'object'
    OR pg_column_size(coalesce(p_candidate_summary,'{}'::jsonb))>4096 THEN
    RAISE EXCEPTION 'Invalid referral code or candidate summary' USING ERRCODE='22023';
  END IF;
  FOR v_key IN SELECT jsonb_object_keys(coalesce(p_candidate_summary,'{}'::jsonb)) LOOP
    IF v_key NOT IN ('age_band','sex_at_birth','site_code','criteria_match_codes','screening_priority') THEN
      RAISE EXCEPTION 'Candidate summary contains a field not permitted for recruitment hand-off' USING ERRCODE='22023';
    END IF;
  END LOOP;
  IF coalesce(p_candidate_summary,'{}'::jsonb) ? 'criteria_match_codes'
    AND jsonb_typeof(p_candidate_summary->'criteria_match_codes')<>'array' THEN
    RAISE EXCEPTION 'criteria_match_codes must be an array' USING ERRCODE='22023';
  END IF;

  SELECT p.org_id INTO v_patient_org
  FROM public.jl_patients p
  WHERE p.id=p_hospital_patient_id AND p.org_id=p_org_id AND coalesce(p.active,true)=true;
  IF v_patient_org IS NULL THEN
    RAISE EXCEPTION 'Hospital patient not found in this organisation' USING ERRCODE='P0002';
  END IF;

  SELECT s.organisation_id,s.status,s.recruitment_enabled,
         s.recruitment_criteria_version,s.ethics_approval_reference,s.ethics_approval_date
    INTO v_study_org,v_study_status,v_recruitment_enabled,
         v_criteria_version,v_ethics_reference,v_ethics_date
  FROM public.jl_trial_studies s
  WHERE s.id=p_study_id;

  IF v_study_org IS DISTINCT FROM p_org_id
    OR v_study_status IS DISTINCT FROM 'active'
    OR v_recruitment_enabled IS DISTINCT FROM true
    OR nullif(v_ethics_reference,'') IS NULL
    OR v_ethics_date IS NULL OR v_ethics_date>current_date
    OR v_criteria_version IS DISTINCT FROM p_criteria_version THEN
    RAISE EXCEPTION 'Study must be active and independently authorised for this criteria version before referral'
      USING ERRCODE='42501';
  END IF;

  INSERT INTO public.jl_trial_recruitment_referrals
    (org_id,study_id,referral_code,candidate_summary,criteria_version,referred_by)
  VALUES
    (p_org_id,p_study_id,btrim(p_referral_code),coalesce(p_candidate_summary,'{}'::jsonb),
     p_criteria_version,auth.uid())
  RETURNING id INTO v_referral_id;

  INSERT INTO private.jl_trial_recruitment_identity_links
    (referral_id,org_id,hospital_patient_id,created_by)
  VALUES(v_referral_id,p_org_id,p_hospital_patient_id,auth.uid());

  INSERT INTO public.jl_trial_recruitment_events
    (org_id,referral_id,event_type,to_status,actor_id,rationale_code)
  VALUES(p_org_id,v_referral_id,'referral_created','referred',auth.uid(),
         'protocol_authorised_recruitment');
  RETURN v_referral_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_authorise_trial_recruitment(uuid,text,date,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_authorise_trial_recruitment(uuid,text,date,text) TO authenticated, service_role;
REVOKE ALL ON FUNCTION public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) TO authenticated, service_role;
