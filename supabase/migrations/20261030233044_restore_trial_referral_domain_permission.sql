-- Preserve the independent Clinical Trials read grant in the Hospital-to-Trial
-- referral path. Active organisation entitlement alone is not member authorisation.

CREATE OR REPLACE FUNCTION public.jl_create_trial_recruitment_referral(
  p_org_id uuid,p_study_id uuid,p_hospital_patient_id uuid,p_referral_code text,
  p_candidate_summary jsonb,p_criteria_version text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'private', 'auth'
AS $function$
DECLARE
  v_referral_id uuid;v_patient_org uuid;v_study_org uuid;v_study_status text;
  v_recruitment_enabled boolean;v_criteria_version text;v_ethics_reference text;
  v_ethics_date date;v_key text;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501';
  END IF;
  IF NOT public.jlight_has_domain_permission(p_org_id,'hospital','write')
    OR NOT public.jlight_has_domain_permission(p_org_id,'clinical_trials','read') THEN
    RAISE EXCEPTION 'Hospital write and Clinical Trials read permissions are required'
      USING ERRCODE='42501';
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
  SELECT p.org_id INTO v_patient_org FROM public.jl_patients p
  WHERE p.id=p_hospital_patient_id AND p.org_id=p_org_id AND coalesce(p.active,true)=true;
  IF v_patient_org IS NULL THEN
    RAISE EXCEPTION 'Hospital patient not found in this organisation' USING ERRCODE='P0002';
  END IF;
  SELECT s.organisation_id,s.status,s.recruitment_enabled,s.recruitment_criteria_version,
    s.ethics_approval_reference,s.ethics_approval_date
  INTO v_study_org,v_study_status,v_recruitment_enabled,v_criteria_version,v_ethics_reference,v_ethics_date
  FROM public.jl_trial_studies s WHERE s.id=p_study_id;
  IF v_study_org IS DISTINCT FROM p_org_id OR v_study_status IS DISTINCT FROM 'active'
    OR v_recruitment_enabled IS DISTINCT FROM true OR nullif(v_ethics_reference,'') IS NULL
    OR v_ethics_date IS NULL OR v_ethics_date>current_date
    OR v_criteria_version IS DISTINCT FROM p_criteria_version THEN
    RAISE EXCEPTION 'Study must be active and independently authorised for this criteria version before referral' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.jl_trial_recruitment_referrals
    (org_id,study_id,referral_code,candidate_summary,criteria_version,referred_by)
  VALUES(p_org_id,p_study_id,btrim(p_referral_code),coalesce(p_candidate_summary,'{}'::jsonb),
    p_criteria_version,auth.uid()) RETURNING id INTO v_referral_id;
  INSERT INTO private.jl_trial_recruitment_identity_links
    (referral_id,org_id,hospital_patient_id,created_by)
  VALUES(v_referral_id,p_org_id,p_hospital_patient_id,auth.uid());
  INSERT INTO public.jl_trial_recruitment_events
    (org_id,referral_id,event_type,to_status,actor_id,rationale_code)
  VALUES(p_org_id,v_referral_id,'referral_created','referred',auth.uid(),'protocol_authorised_recruitment');
  RETURN v_referral_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_create_trial_recruitment_referral(uuid,uuid,uuid,text,jsonb,text) TO authenticated, service_role;
