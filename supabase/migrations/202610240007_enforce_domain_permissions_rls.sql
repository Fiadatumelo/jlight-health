-- Enforce domain grants at the database boundary, not only in the Settings UI.
-- Staging-first: retain existing tenant fences and add restrictive domain fences.
BEGIN;

CREATE OR REPLACE FUNCTION public.jlight_has_domain_permission(
  p_organization_id uuid,
  p_domain text,
  p_access text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
  SELECT CASE p_access
    WHEN 'read' THEN EXISTS (
      SELECT 1
      FROM public.jlight_organization_memberships m
      JOIN public.jlight_membership_domain_permissions dp
        ON dp.organization_id = m.organization_id
       AND dp.auth_subject = m.auth_subject
      WHERE m.organization_id = p_organization_id
        AND m.auth_subject = auth.uid()
        AND m.active = true
        AND dp.domain = p_domain
        AND dp.can_read = true
    )
    WHEN 'write' THEN EXISTS (
      SELECT 1
      FROM public.jlight_organization_memberships m
      JOIN public.jlight_membership_domain_permissions dp
        ON dp.organization_id = m.organization_id
       AND dp.auth_subject = m.auth_subject
      WHERE m.organization_id = p_organization_id
        AND m.auth_subject = auth.uid()
        AND m.active = true
        AND dp.domain = p_domain
        AND dp.can_write = true
        AND dp.can_read = true
    )
    WHEN 'report' THEN EXISTS (
      SELECT 1
      FROM public.jlight_organization_memberships m
      JOIN public.jlight_membership_domain_permissions dp
        ON dp.organization_id = m.organization_id
       AND dp.auth_subject = m.auth_subject
      WHERE m.organization_id = p_organization_id
        AND m.auth_subject = auth.uid()
        AND m.active = true
        AND dp.domain = p_domain
        AND dp.can_report = true
        AND dp.can_read = true
    )
    ELSE false
  END;
$function$;

CREATE OR REPLACE FUNCTION public.jlight_finding_domain_access(
  p_organization_id uuid,
  p_finding_id uuid,
  p_access text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
DECLARE
  v_sources uuid[];
BEGIN
  IF auth.uid() IS NULL OR p_organization_id IS NULL OR p_finding_id IS NULL
     OR p_access NOT IN ('read','write','report') THEN
    RETURN false;
  END IF;

  SELECT f.source_observation_ids
    INTO v_sources
  FROM public.jl_intelligence_findings f
  WHERE f.id = p_finding_id
    AND f.organisation_id = p_organization_id;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  IF coalesce(cardinality(v_sources), 0) = 0 THEN
    RETURN public.jlight_has_domain_permission(p_organization_id, 'hospital', p_access)
        OR public.jlight_has_domain_permission(p_organization_id, 'laboratory', p_access)
        OR public.jlight_has_domain_permission(p_organization_id, 'bioinformatics', p_access);
  END IF;

  -- A cross-section finding is visible/reviewable only if the caller has the
  -- required permission for every source section contributing to that finding.
  RETURN NOT EXISTS (
    SELECT 1
    FROM unnest(v_sources) AS source_id
    LEFT JOIN public.jl_source_observations o
      ON o.id = source_id
     AND o.organisation_id = p_organization_id
    WHERE o.id IS NULL
       OR NOT public.jlight_has_domain_permission(p_organization_id, o.section, p_access)
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) TO authenticated;
REVOKE ALL ON FUNCTION public.jlight_finding_domain_access(uuid,uuid,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_finding_domain_access(uuid,uuid,text) TO authenticated;

-- Encounter types are mapped to the relevant operating domain.
DROP POLICY IF EXISTS jlight_encounters_domain_read ON public.jl_encounters;
CREATE POLICY jlight_encounters_domain_read ON public.jl_encounters
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.jlight_has_domain_permission(
    organisation_id,
    CASE WHEN encounter_type = 'laboratory' THEN 'laboratory' ELSE 'hospital' END,
    'read'
  ));

DROP POLICY IF EXISTS jlight_encounters_domain_write ON public.jl_encounters;
CREATE POLICY jlight_encounters_domain_write ON public.jl_encounters
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    public.jlight_has_domain_permission(
      organisation_id,
      CASE WHEN encounter_type = 'laboratory' THEN 'laboratory' ELSE 'hospital' END,
      'write'
    )
    AND created_by = auth.uid()
  );

DROP POLICY IF EXISTS jlight_encounters_domain_update ON public.jl_encounters;
CREATE POLICY jlight_encounters_domain_update ON public.jl_encounters
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.jlight_has_domain_permission(
    organisation_id,
    CASE WHEN encounter_type = 'laboratory' THEN 'laboratory' ELSE 'hospital' END,
    'write'
  ))
  WITH CHECK (public.jlight_has_domain_permission(
    organisation_id,
    CASE WHEN encounter_type = 'laboratory' THEN 'laboratory' ELSE 'hospital' END,
    'write'
  ));

-- Source observations are fenced by their explicit source section.
DROP POLICY IF EXISTS jlight_observations_domain_read ON public.jl_source_observations;
CREATE POLICY jlight_observations_domain_read ON public.jl_source_observations
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.jlight_has_domain_permission(organisation_id, section, 'read'));

DROP POLICY IF EXISTS jlight_observations_domain_write ON public.jl_source_observations;
CREATE POLICY jlight_observations_domain_write ON public.jl_source_observations
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    public.jlight_has_domain_permission(organisation_id, section, 'write')
    AND created_by = auth.uid()
  );

DROP POLICY IF EXISTS jlight_observations_domain_update ON public.jl_source_observations;
CREATE POLICY jlight_observations_domain_update ON public.jl_source_observations
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.jlight_has_domain_permission(organisation_id, section, 'write'))
  WITH CHECK (public.jlight_has_domain_permission(organisation_id, section, 'write'));

-- Findings that cite multiple observations require permission for every cited
-- source section. Findings without source references require at least one
-- explicit domain grant in the organisation.
DROP POLICY IF EXISTS jlight_findings_domain_read ON public.jl_intelligence_findings;
CREATE POLICY jlight_findings_domain_read ON public.jl_intelligence_findings
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.jlight_finding_domain_access(organisation_id, id, 'read'));

DROP POLICY IF EXISTS jlight_findings_domain_insert ON public.jl_intelligence_findings;
CREATE POLICY jlight_findings_domain_insert ON public.jl_intelligence_findings
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    CASE
      WHEN coalesce(cardinality(source_observation_ids), 0) = 0 THEN
        public.jlight_has_domain_permission(organisation_id, 'hospital', 'write')
        OR public.jlight_has_domain_permission(organisation_id, 'laboratory', 'write')
        OR public.jlight_has_domain_permission(organisation_id, 'bioinformatics', 'write')
      ELSE NOT EXISTS (
        SELECT 1
        FROM unnest(source_observation_ids) AS source_id
        LEFT JOIN public.jl_source_observations o
          ON o.id = source_id
         AND o.organisation_id = jl_intelligence_findings.organisation_id
        WHERE o.id IS NULL
           OR NOT public.jlight_has_domain_permission(organisation_id, o.section, 'write')
      )
    END
    AND (created_by IS NULL OR created_by = auth.uid())
  );

DROP POLICY IF EXISTS jlight_findings_domain_update ON public.jl_intelligence_findings;
CREATE POLICY jlight_findings_domain_update ON public.jl_intelligence_findings
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.jlight_finding_domain_access(organisation_id, id, 'write'))
  WITH CHECK (
    CASE
      WHEN coalesce(cardinality(source_observation_ids), 0) = 0 THEN
        public.jlight_has_domain_permission(organisation_id, 'hospital', 'write')
        OR public.jlight_has_domain_permission(organisation_id, 'laboratory', 'write')
        OR public.jlight_has_domain_permission(organisation_id, 'bioinformatics', 'write')
      ELSE NOT EXISTS (
        SELECT 1
        FROM unnest(source_observation_ids) AS source_id
        LEFT JOIN public.jl_source_observations o
          ON o.id = source_id
         AND o.organisation_id = jl_intelligence_findings.organisation_id
        WHERE o.id IS NULL
           OR NOT public.jlight_has_domain_permission(organisation_id, o.section, 'write')
      )
    END
  );

-- Review history inherits the permissions of its linked finding.
DROP POLICY IF EXISTS jlight_finding_events_domain_read ON public.jl_finding_review_events;
CREATE POLICY jlight_finding_events_domain_read ON public.jl_finding_review_events
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.jlight_finding_domain_access(organisation_id, finding_id, 'read'));

DROP POLICY IF EXISTS jlight_finding_events_domain_insert ON public.jl_finding_review_events;
CREATE POLICY jlight_finding_events_domain_insert ON public.jl_finding_review_events
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    public.jlight_finding_domain_access(organisation_id, finding_id, 'write')
    AND actor_user_id = auth.uid()
  );

-- The SECURITY DEFINER review RPC bypasses table RLS, so it must independently
-- enforce the same source-domain permission check.
CREATE OR REPLACE FUNCTION public.jl_review_intelligence_finding(
  p_finding_id uuid,
  p_action text,
  p_note text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, auth
AS $function$
DECLARE
  v_uid uuid := auth.uid();
  v_finding public.jl_intelligence_findings%rowtype;
  v_status text;
  v_note text := nullif(btrim(p_note), '');
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Authentication required' USING ERRCODE = '28000';
  END IF;
  IF p_finding_id IS NULL OR p_action NOT IN ('opened','assigned','commented','resolved','reopened','dismissed') THEN
    RAISE EXCEPTION 'Finding and a supported review action are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_finding
  FROM public.jl_intelligence_findings
  WHERE id = p_finding_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Finding not found' USING ERRCODE = 'P0002';
  END IF;

  IF NOT public.jl_has_org_role(
    v_finding.organisation_id,
    ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer']::text[]
  ) OR NOT public.jlight_finding_domain_access(v_finding.organisation_id, v_finding.id, 'write') THEN
    RAISE EXCEPTION 'You do not have permission to review this finding in its source domain(s)' USING ERRCODE = '42501';
  END IF;

  IF v_note IS NOT NULL AND length(v_note) > 4000 THEN
    RAISE EXCEPTION 'Review note must be 4000 characters or fewer' USING ERRCODE = '22023';
  END IF;

  v_status := v_finding.status;
  IF p_action = 'resolved' THEN
    v_status := 'resolved';
  ELSIF p_action = 'dismissed' THEN
    v_status := 'dismissed';
  ELSIF p_action = 'reopened' THEN
    v_status := 'open';
  ELSIF p_action = 'opened' AND v_status = 'open' THEN
    v_status := 'in_review';
  END IF;

  INSERT INTO public.jl_finding_review_events
    (organisation_id, finding_id, action, note, actor_user_id)
  VALUES
    (v_finding.organisation_id, v_finding.id, p_action, v_note, v_uid);

  IF v_status IS DISTINCT FROM v_finding.status THEN
    UPDATE public.jl_intelligence_findings
    SET status = v_status,
        reviewed_at = CASE WHEN p_action IN ('resolved','dismissed') THEN now() WHEN p_action = 'reopened' THEN NULL ELSE reviewed_at END,
        reviewed_by = CASE WHEN p_action IN ('resolved','dismissed') THEN v_uid WHEN p_action = 'reopened' THEN NULL ELSE reviewed_by END,
        resolution_note = CASE WHEN p_action IN ('resolved','dismissed') THEN v_note WHEN p_action = 'reopened' THEN NULL ELSE resolution_note END
    WHERE id = v_finding.id;
  ELSIF p_action IN ('resolved','dismissed') THEN
    UPDATE public.jl_intelligence_findings
    SET reviewed_at = now(), reviewed_by = v_uid, resolution_note = v_note
    WHERE id = v_finding.id;
  END IF;

  RETURN jsonb_build_object('success', true, 'finding_id', v_finding.id, 'action', p_action, 'status', v_status);
END;
$function$;

REVOKE ALL ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_has_domain_permission(uuid,text,text) TO authenticated;
REVOKE ALL ON FUNCTION public.jlight_finding_domain_access(uuid,uuid,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jlight_finding_domain_access(uuid,uuid,text) TO authenticated;
REVOKE ALL ON FUNCTION public.jl_review_intelligence_finding(uuid,text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_review_intelligence_finding(uuid,text,text) TO authenticated;

COMMIT;
