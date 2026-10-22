-- JLIGHT integrity guards for cross-section links and review history.
-- Apply only after the foundation migration has passed staging schema checks.
BEGIN;

CREATE OR REPLACE FUNCTION public.jl_validate_finding_links()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  observation_id uuid;
BEGIN
  IF NEW.patient_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.jl_patients p
    WHERE p.id = NEW.patient_id AND p.organisation_id = NEW.organisation_id
  ) THEN
    RAISE EXCEPTION 'Finding patient must belong to the same organisation';
  END IF;

  IF NEW.encounter_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM public.jl_encounters e
    WHERE e.id = NEW.encounter_id
      AND e.organisation_id = NEW.organisation_id
      AND (NEW.patient_id IS NULL OR e.patient_id = NEW.patient_id)
  ) THEN
    RAISE EXCEPTION 'Finding encounter must match its patient and organisation';
  END IF;

  FOREACH observation_id IN ARRAY COALESCE(NEW.source_observation_ids, '{}'::uuid[])
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM public.jl_source_observations o
      WHERE o.id = observation_id
        AND o.organisation_id = NEW.organisation_id
        AND (NEW.patient_id IS NULL OR o.patient_id = NEW.patient_id)
        AND (NEW.encounter_id IS NULL OR o.encounter_id IS NULL OR o.encounter_id = NEW.encounter_id)
    ) THEN
      RAISE EXCEPTION 'Finding source observations must match the finding organisation and context';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.jl_validate_finding_links() FROM PUBLIC;
DROP TRIGGER IF EXISTS jl_finding_links_guard ON public.jl_intelligence_findings;
CREATE TRIGGER jl_finding_links_guard
BEFORE INSERT OR UPDATE ON public.jl_intelligence_findings
FOR EACH ROW EXECUTE FUNCTION public.jl_validate_finding_links();

CREATE OR REPLACE FUNCTION public.jl_validate_review_event_finding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.jl_intelligence_findings f
    WHERE f.id = NEW.finding_id AND f.organisation_id = NEW.organisation_id
  ) THEN
    RAISE EXCEPTION 'Review event and finding must belong to the same organisation';
  END IF;
  IF NEW.actor_user_id IS DISTINCT FROM auth.uid() THEN
    RAISE EXCEPTION 'Review event actor must be the authenticated user';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.jl_validate_review_event_finding() FROM PUBLIC;
DROP TRIGGER IF EXISTS jl_review_event_finding_guard ON public.jl_finding_review_events;
CREATE TRIGGER jl_review_event_finding_guard
BEFORE INSERT OR UPDATE ON public.jl_finding_review_events
FOR EACH ROW EXECUTE FUNCTION public.jl_validate_review_event_finding();

-- Review events are append-only for browser clients. The policy layer also
-- omits UPDATE/DELETE grants; this trigger provides a second guardrail.
CREATE OR REPLACE FUNCTION public.jl_prevent_review_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
  RAISE EXCEPTION 'Finding review events are append-only';
END;
$$;
REVOKE ALL ON FUNCTION public.jl_prevent_review_event_mutation() FROM PUBLIC;
DROP TRIGGER IF EXISTS jl_review_event_immutable_guard ON public.jl_finding_review_events;
CREATE TRIGGER jl_review_event_immutable_guard
BEFORE UPDATE OR DELETE ON public.jl_finding_review_events
FOR EACH ROW EXECUTE FUNCTION public.jl_prevent_review_event_mutation();

COMMIT;
