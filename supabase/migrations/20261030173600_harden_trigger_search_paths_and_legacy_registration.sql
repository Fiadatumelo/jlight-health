-- Harden trigger function name resolution and add an explicit auth check to the
-- legacy registration wrapper. These changes do not alter trigger semantics.
CREATE OR REPLACE FUNCTION public.jl_validate_finding_links()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public'
AS $function$
DECLARE observation_id uuid;
BEGIN
 IF NEW.patient_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM public.jl_patients p WHERE p.id=NEW.patient_id AND p.org_id=NEW.organisation_id
 ) THEN RAISE EXCEPTION 'Finding patient must belong to the same organisation'; END IF;
 IF NEW.encounter_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM public.jl_encounters e WHERE e.id=NEW.encounter_id
   AND e.organisation_id=NEW.organisation_id
   AND (NEW.patient_id IS NULL OR e.patient_id=NEW.patient_id)
 ) THEN RAISE EXCEPTION 'Finding encounter must match its patient and organisation'; END IF;
 FOREACH observation_id IN ARRAY COALESCE(NEW.source_observation_ids,'{}'::uuid[])
 LOOP
  IF NOT EXISTS (
   SELECT 1 FROM public.jl_source_observations o WHERE o.id=observation_id
    AND o.organisation_id=NEW.organisation_id
    AND (NEW.patient_id IS NULL OR o.patient_id=NEW.patient_id)
    AND (NEW.encounter_id IS NULL OR o.encounter_id IS NULL OR o.encounter_id=NEW.encounter_id)
  ) THEN RAISE EXCEPTION 'Finding source observations must match the finding organisation and context'; END IF;
 END LOOP;
 RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_validate_review_event_finding()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM public.jl_intelligence_findings f
  WHERE f.id=NEW.finding_id AND f.organisation_id=NEW.organisation_id
 ) THEN RAISE EXCEPTION 'Review event and finding must belong to the same organisation'; END IF;
 IF NEW.actor_user_id IS DISTINCT FROM auth.uid() THEN
  RAISE EXCEPTION 'Review event actor must be the authenticated user';
 END IF;
 RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.jl_create_organisation(
 p_name text DEFAULT 'JLIGHT Health Intelligence Platform',
 p_role text DEFAULT 'Laboratory'
)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','public','auth'
AS $function$
DECLARE v_uid uuid:=auth.uid(); v_key text;
BEGIN
 IF v_uid IS NULL THEN RAISE EXCEPTION 'Verified authentication required' USING ERRCODE='42501'; END IF;
 v_key:=CASE lower(btrim(coalesce(p_role,'')))
  WHEN 'hospital' THEN 'hospital' WHEN 'laboratory' THEN 'laboratory'
  WHEN 'bioinformatics' THEN 'bioinformatics' WHEN 'trial' THEN 'clinical_trials'
  WHEN 'clinical_trials' THEN 'clinical_trials' ELSE NULL END;
 IF v_key IS NULL THEN RAISE EXCEPTION 'Select a valid JLIGHT pathway' USING ERRCODE='22023'; END IF;
 RETURN public.jl_register_organisation_multi(p_name,ARRAY[v_key]);
END;
$function$;
REVOKE ALL ON FUNCTION public.jl_create_organisation(text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.jl_create_organisation(text,text) TO authenticated,service_role;
