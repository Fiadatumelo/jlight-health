-- Replace hard-coded report job-title checks with organisation-configured domain permissions.
-- Intentionally does not alter organisation codes, code generation, onboarding, or invitations.
-- Report archive deletion requires both report entitlement and the existing write entitlement
-- for every source domain until a dedicated delete entitlement is introduced end-to-end.

BEGIN;

CREATE OR REPLACE FUNCTION private.jl_report_access_allowed(
  p_action text,
  p_workspace text,
  p_source_systems jsonb
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, private, auth
AS $function$
DECLARE
  v_org_id uuid;
  v_domains text[] := ARRAY[]::text[];
  v_source text;
  v_domain text;
BEGIN
  IF auth.uid() IS NULL OR p_action NOT IN ('read', 'write', 'delete') THEN
    RETURN false;
  END IF;

  v_org_id := private.jl_current_org_id();
  IF v_org_id IS NULL THEN
    RETURN false;
  END IF;

  IF p_source_systems IS NOT NULL
     AND jsonb_typeof(p_source_systems) IS DISTINCT FROM 'array' THEN
    RETURN false;
  END IF;

  IF p_workspace = 'Trial' THEN
    IF private.jl_current_org_role() IS DISTINCT FROM 'Trial' THEN
      RETURN false;
    END IF;

    IF EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(coalesce(p_source_systems, '[]'::jsonb)) s(source)
      WHERE s.source IS DISTINCT FROM 'Clinical Trials'
    ) THEN
      RETURN false;
    END IF;

    v_domains := ARRAY['clinical_trials'];
  ELSE
    -- Trial organisations must never read or archive non-trial reports.
    IF private.jl_current_org_role() = 'Trial' THEN
      RETURN false;
    END IF;

    IF coalesce(jsonb_array_length(p_source_systems), 0) = 0 THEN
      v_domain := CASE p_workspace
        WHEN 'Hospital' THEN 'hospital'
        WHEN 'Laboratory' THEN 'laboratory'
        WHEN 'Bioinformatics' THEN 'bioinformatics'
        ELSE NULL
      END;
      IF v_domain IS NULL THEN
        RETURN false;
      END IF;
      v_domains := ARRAY[v_domain];
    ELSE
      FOR v_source IN
        SELECT jsonb_array_elements_text(p_source_systems)
      LOOP
        CASE v_source
          WHEN 'Hospital' THEN v_domain := 'hospital';
          WHEN 'Laboratory' THEN v_domain := 'laboratory';
          WHEN 'Bioinformatics' THEN v_domain := 'bioinformatics';
          WHEN 'JLIGHT Intelligence' THEN
            v_domains := array_cat(v_domains, ARRAY['hospital','laboratory','bioinformatics']);
            v_domain := NULL;
          ELSE
            RETURN false;
        END CASE;

        IF v_domain IS NOT NULL AND NOT (v_domain = ANY(v_domains)) THEN
          v_domains := array_append(v_domains, v_domain);
        END IF;
      END LOOP;
    END IF;
  END IF;

  IF cardinality(v_domains) = 0 THEN
    RETURN false;
  END IF;

  FOREACH v_domain IN ARRAY v_domains LOOP
    -- Report generation and archive reading follow the organisation's explicit
    -- can_report assignment for each source domain.
    IF NOT public.jlight_has_domain_permission(v_org_id, v_domain, 'report') THEN
      RETURN false;
    END IF;

    -- The current permission model has no separate can_delete flag. Fail safely:
    -- archive deletion also requires the organisation-granted write permission.
    IF p_action = 'delete'
       AND NOT public.jlight_has_domain_permission(v_org_id, v_domain, 'write') THEN
      RETURN false;
    END IF;
  END LOOP;

  RETURN true;
END;
$function$;

REVOKE ALL ON FUNCTION private.jl_report_access_allowed(text,text,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.jl_report_access_allowed(text,text,jsonb) TO authenticated;

CREATE OR REPLACE FUNCTION public.jl_report_access_allowed(
  p_action text,
  p_workspace text DEFAULT NULL,
  p_source_systems jsonb DEFAULT NULL
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, public, private, auth
AS $function$
  SELECT private.jl_report_access_allowed(p_action, p_workspace, p_source_systems);
$function$;

REVOKE ALL ON FUNCTION public.jl_report_access_allowed(text,text,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.jl_report_access_allowed(text,text,jsonb) TO authenticated;

DROP POLICY IF EXISTS jl_entries_reports_select ON public.jl_entries;
CREATE POLICY jl_entries_reports_select ON public.jl_entries
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (
    domain IS DISTINCT FROM 'reports'
    OR private.jl_report_access_allowed(
      'read', payload ->> 'workspace',
      coalesce(payload -> 'sourceSystems', payload -> 'json' -> 'sourceSystems')
    )
  );

DROP POLICY IF EXISTS jl_entries_reports_insert ON public.jl_entries;
CREATE POLICY jl_entries_reports_insert ON public.jl_entries
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (
    domain IS DISTINCT FROM 'reports'
    OR private.jl_report_access_allowed(
      'write', payload ->> 'workspace',
      coalesce(payload -> 'sourceSystems', payload -> 'json' -> 'sourceSystems')
    )
  );

DROP POLICY IF EXISTS jl_entries_reports_update ON public.jl_entries;
CREATE POLICY jl_entries_reports_update ON public.jl_entries
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (
    domain IS DISTINCT FROM 'reports'
    OR private.jl_report_access_allowed(
      'write', payload ->> 'workspace',
      coalesce(payload -> 'sourceSystems', payload -> 'json' -> 'sourceSystems')
    )
  )
  WITH CHECK (
    domain IS DISTINCT FROM 'reports'
    OR private.jl_report_access_allowed(
      'write', payload ->> 'workspace',
      coalesce(payload -> 'sourceSystems', payload -> 'json' -> 'sourceSystems')
    )
  );

DROP POLICY IF EXISTS jl_entries_reports_delete ON public.jl_entries;
CREATE POLICY jl_entries_reports_delete ON public.jl_entries
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (
    domain IS DISTINCT FROM 'reports'
    OR private.jl_report_access_allowed(
      'delete', payload ->> 'workspace',
      coalesce(payload -> 'sourceSystems', payload -> 'json' -> 'sourceSystems')
    )
  );

COMMIT;
