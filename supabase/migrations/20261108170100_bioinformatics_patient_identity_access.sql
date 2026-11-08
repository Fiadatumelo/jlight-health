-- Patient identity is a Hospital/Laboratory data domain.
-- Bioinformatics can associate a run to an exact canonical patient UUID through
-- the authenticated backend API, but must not read or write patient demographics.
BEGIN;

CREATE OR REPLACE FUNCTION private.jlight_entry_domain_access_allowed(
  p_org_id uuid,
  p_domain text,
  p_payload jsonb,
  p_access text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'private', 'auth'
AS $function$
DECLARE
  v_access text := CASE WHEN p_access = 'delete' THEN 'write' ELSE p_access END;
  v_sources jsonb;
BEGIN
  IF auth.uid() IS NULL OR p_org_id IS NULL
     OR p_access NOT IN ('read', 'write', 'delete')
     OR p_org_id IS DISTINCT FROM private.jl_current_org_id() THEN
    RETURN false;
  END IF;

  IF p_domain = 'reports' THEN
    v_sources := coalesce(
      p_payload -> 'sourceSystems',
      (p_payload -> 'json') -> 'sourceSystems'
    );
    RETURN private.jl_report_access_allowed(
      p_access,
      p_payload ->> 'workspace',
      v_sources
    );
  ELSIF p_domain = 'patients' THEN
    RETURN public.jlight_has_domain_permission(p_org_id, 'hospital', v_access)
        OR public.jlight_has_domain_permission(p_org_id, 'laboratory', v_access);
  ELSIF p_domain IN ('labOrders', 'samples', 'results', 'qcRuns', 'instruments') THEN
    RETURN public.jlight_has_domain_permission(p_org_id, 'laboratory', v_access);
  ELSIF p_domain IN ('admissions', 'wards', 'clinicalOrders', 'infections') THEN
    RETURN public.jlight_has_domain_permission(p_org_id, 'hospital', v_access);
  ELSIF p_domain IN ('bioRuns', 'bioAccessions', 'bioQc', 'bioAmr') THEN
    RETURN public.jlight_has_domain_permission(p_org_id, 'bioinformatics', v_access);
  ELSIF p_domain IN ('protocols', 'participants', 'visits', 'adverseEvents', 'consents', 'deviations') THEN
    RETURN public.jlight_has_domain_permission(p_org_id, 'clinical_trials', v_access);
  END IF;

  RETURN false;
END;
$function$;

DROP POLICY IF EXISTS jl_patients_domain_select ON public.jl_patients;
CREATE POLICY jl_patients_domain_select ON public.jl_patients
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (
    org_id = (SELECT private.jl_current_org_id())
    AND (
      (SELECT public.jlight_has_domain_permission(org_id, 'hospital', 'read'))
      OR (SELECT public.jlight_has_domain_permission(org_id, 'laboratory', 'read'))
    )
  );

DROP POLICY IF EXISTS jl_patients_domain_insert ON public.jl_patients;
CREATE POLICY jl_patients_domain_insert ON public.jl_patients
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    org_id = (SELECT private.jl_current_org_id())
    AND (
      (SELECT public.jlight_has_domain_permission(org_id, 'hospital', 'write'))
      OR (SELECT public.jlight_has_domain_permission(org_id, 'laboratory', 'write'))
    )
  );

DROP POLICY IF EXISTS jl_patients_domain_update ON public.jl_patients;
CREATE POLICY jl_patients_domain_update ON public.jl_patients
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (
    org_id = (SELECT private.jl_current_org_id())
    AND (
      (SELECT public.jlight_has_domain_permission(org_id, 'hospital', 'write'))
      OR (SELECT public.jlight_has_domain_permission(org_id, 'laboratory', 'write'))
    )
  )
  WITH CHECK (
    org_id = (SELECT private.jl_current_org_id())
    AND (
      (SELECT public.jlight_has_domain_permission(org_id, 'hospital', 'write'))
      OR (SELECT public.jlight_has_domain_permission(org_id, 'laboratory', 'write'))
    )
  );

DROP POLICY IF EXISTS jl_patients_domain_delete ON public.jl_patients;
CREATE POLICY jl_patients_domain_delete ON public.jl_patients
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (
    org_id = (SELECT private.jl_current_org_id())
    AND (
      (SELECT public.jlight_has_domain_permission(org_id, 'hospital', 'write'))
      OR (SELECT public.jlight_has_domain_permission(org_id, 'laboratory', 'write'))
    )
  );

COMMIT;
