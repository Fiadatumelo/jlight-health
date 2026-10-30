-- Recruitment approval must be independent of the organisation and study creator.
-- This migration is additive and does not alter production data or entitlements.

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
BEGIN
  IF auth.uid() IS NULL OR NOT public.jl_is_platform_super_admin() THEN
    RAISE EXCEPTION 'Independent JLIGHT Platform Administrator approval is required'
      USING ERRCODE='42501';
  END IF;

  IF nullif(btrim(p_ethics_approval_reference),'') IS NULL
    OR length(p_ethics_approval_reference)>200
    OR p_ethics_approval_date IS NULL
    OR p_ethics_approval_date>current_date
    OR nullif(btrim(p_criteria_version),'') IS NULL
    OR length(p_criteria_version)>80 THEN
    RAISE EXCEPTION 'Valid ethics approval reference, date and recruitment criteria version are required'
      USING ERRCODE='22023';
  END IF;

  SELECT organisation_id,created_by
    INTO v_org_id,v_created_by
  FROM public.jl_trial_studies
  WHERE id=p_study_id
  FOR UPDATE;

  IF v_org_id IS NULL THEN
    RAISE EXCEPTION 'Study not found' USING ERRCODE='P0002';
  END IF;

  IF v_created_by=auth.uid()
    OR EXISTS (
      SELECT 1 FROM public.jlight_organization_memberships m
      WHERE m.organization_id=v_org_id
        AND m.auth_subject=auth.uid()
        AND m.active=true
    )
    OR EXISTS (
      SELECT 1 FROM public.jl_org_memberships m
      WHERE m.organisation_id=v_org_id
        AND m.user_id=auth.uid()
        AND m.status='active'
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
     jsonb_build_object(
       'criteria_version',btrim(p_criteria_version),
       'ethics_approval_date',p_ethics_approval_date
     ));
END;
$function$;

REVOKE ALL ON FUNCTION public.jl_authorise_trial_recruitment(uuid,text,date,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_authorise_trial_recruitment(uuid,text,date,text) TO authenticated, service_role;
