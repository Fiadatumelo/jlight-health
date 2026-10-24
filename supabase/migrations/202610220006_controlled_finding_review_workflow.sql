-- Restrict broad finding edits and provide a controlled review workflow.
BEGIN;

DROP POLICY IF EXISTS jl_findings_update ON public.jl_intelligence_findings;
CREATE POLICY jl_findings_update ON public.jl_intelligence_findings
FOR UPDATE TO authenticated
USING (public.jl_has_org_role(organisation_id, ARRAY['owner','org_admin','hospital','laboratory','bioinformatics']::text[]))
WITH CHECK (public.jl_has_org_role(organisation_id, ARRAY['owner','org_admin','hospital','laboratory','bioinformatics']::text[]));

CREATE OR REPLACE FUNCTION public.jl_review_finding(
  p_finding_id uuid,
  p_action text,
  p_note text DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  f public.jl_intelligence_findings%ROWTYPE;
  next_status text;
  actor uuid := auth.uid();
BEGIN
  IF actor IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '42501';
  END IF;
  IF p_action NOT IN ('opened','commented','resolved','reopened','dismissed') THEN
    RAISE EXCEPTION 'Unsupported review action';
  END IF;
  IF p_note IS NOT NULL AND length(p_note) > 4000 THEN
    RAISE EXCEPTION 'Review note is too long';
  END IF;

  SELECT * INTO f
  FROM public.jl_intelligence_findings
  WHERE id = p_finding_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Finding not found';
  END IF;
  IF NOT public.jl_has_org_role(f.organisation_id,
      ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer']::text[]) THEN
    RAISE EXCEPTION 'Not authorised to review this finding' USING ERRCODE = '42501';
  END IF;

  next_status := CASE p_action
    WHEN 'resolved' THEN 'resolved'
    WHEN 'dismissed' THEN 'dismissed'
    WHEN 'reopened' THEN 'open'
    WHEN 'opened' THEN CASE WHEN f.status = 'open' THEN 'open' ELSE 'in_review' END
    ELSE f.status
  END;

  UPDATE public.jl_intelligence_findings
  SET status = next_status,
      reviewed_at = CASE WHEN p_action = 'commented' THEN reviewed_at ELSE now() END,
      reviewed_by = CASE WHEN p_action = 'commented' THEN reviewed_by ELSE actor END,
      resolution_note = CASE
        WHEN p_action IN ('resolved','dismissed') THEN p_note
        WHEN p_action = 'reopened' THEN NULL
        ELSE resolution_note
      END
  WHERE id = p_finding_id;

  INSERT INTO public.jl_finding_review_events
    (organisation_id, finding_id, action, note, actor_user_id)
  VALUES (f.organisation_id, f.id, p_action, p_note, actor);
  RETURN f.id;
END;
$$;

REVOKE ALL ON FUNCTION public.jl_review_finding(uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.jl_review_finding(uuid,text,text) TO authenticated;
COMMIT;
