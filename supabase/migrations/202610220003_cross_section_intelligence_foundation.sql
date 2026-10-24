-- JLIGHT secure cross-section intelligence foundation.
-- Apply to a staging project first. Do not disable RLS or treat org codes as credentials.
BEGIN;

CREATE TABLE IF NOT EXISTS public.jl_org_memberships (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 access_role text NOT NULL CHECK (access_role IN ('owner','org_admin','hospital','laboratory','bioinformatics','clinical_trial','reviewer','read_only')),
 status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','revoked')),
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid REFERENCES auth.users(id),
 UNIQUE (organisation_id,user_id)
);
CREATE INDEX IF NOT EXISTS jl_org_memberships_user_org_idx ON public.jl_org_memberships(user_id,organisation_id) WHERE status='active';
INSERT INTO public.jl_org_memberships(organisation_id,user_id,access_role,status,created_by)
 SELECT id,owner_user_id,'owner','active',owner_user_id FROM public.jl_organisations WHERE owner_user_id IS NOT NULL
 ON CONFLICT(organisation_id,user_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.jl_is_org_member(p_org_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM public.jl_org_memberships m WHERE m.organisation_id=p_org_id AND m.user_id=auth.uid() AND m.status='active');
$$;
REVOKE ALL ON FUNCTION public.jl_is_org_member(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.jl_is_org_member(uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public.jl_has_org_role(p_org_id uuid,p_roles text[])
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM public.jl_org_memberships m WHERE m.organisation_id=p_org_id AND m.user_id=auth.uid() AND m.status='active' AND m.access_role=ANY(p_roles));
$$;
REVOKE ALL ON FUNCTION public.jl_has_org_role(uuid,text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.jl_has_org_role(uuid,text[]) TO authenticated;

ALTER TABLE public.jl_org_memberships ENABLE ROW LEVEL SECURITY;
-- Do not FORCE RLS on this lookup table: the narrowly scoped SECURITY DEFINER
-- membership-check functions must read it without recursive policy evaluation.
-- Clients can only list their own memberships; no browser writes are granted.
DROP POLICY IF EXISTS jl_memberships_read_self_or_admin ON public.jl_org_memberships;
DROP POLICY IF EXISTS jl_memberships_read_self ON public.jl_org_memberships;
CREATE POLICY jl_memberships_read_self ON public.jl_org_memberships FOR SELECT TO authenticated
 USING(user_id=auth.uid());
-- No client membership writes; invitation provisioning requires a trusted server flow.

-- Reuse the existing JLIGHT patient registry (org_id schema); do not replace it.

CREATE TABLE IF NOT EXISTS public.jl_encounters (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 patient_id uuid NOT NULL REFERENCES public.jl_patients(id) ON DELETE RESTRICT,
 source_system text NOT NULL,
 source_encounter_ref text NOT NULL,
 encounter_type text NOT NULL CHECK(encounter_type IN ('hospital','laboratory','outpatient','emergency','other')),
 occurred_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','completed','cancelled')),
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 UNIQUE(organisation_id,source_system,source_encounter_ref)
);
CREATE INDEX IF NOT EXISTS jl_encounters_patient_time_idx ON public.jl_encounters(organisation_id,patient_id,occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.jl_source_observations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 patient_id uuid NOT NULL REFERENCES public.jl_patients(id) ON DELETE RESTRICT,
 encounter_id uuid REFERENCES public.jl_encounters(id) ON DELETE RESTRICT,
 source_system text NOT NULL,
 source_record_ref text NOT NULL,
 section text NOT NULL CHECK(section IN ('hospital','laboratory','bioinformatics')),
 observation_type text NOT NULL,
 observed_at timestamptz NOT NULL,
 value_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(value_json)='object'),
 provenance_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(provenance_json)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 UNIQUE(organisation_id,source_system,source_record_ref)
);
CREATE INDEX IF NOT EXISTS jl_observations_patient_time_idx ON public.jl_source_observations(organisation_id,patient_id,observed_at DESC);

CREATE TABLE IF NOT EXISTS public.jl_intelligence_findings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 patient_id uuid REFERENCES public.jl_patients(id) ON DELETE RESTRICT,
 encounter_id uuid REFERENCES public.jl_encounters(id) ON DELETE RESTRICT,
 finding_type text NOT NULL,
 severity text NOT NULL CHECK(severity IN ('info','low','moderate','high','critical')),
 status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_review','resolved','dismissed')),
 title text NOT NULL CHECK(length(btrim(title)) BETWEEN 1 AND 240),
 explanation text NOT NULL CHECK(length(btrim(explanation)) BETWEEN 1 AND 4000),
 source_observation_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
 suggested_next_step text,
 rule_version text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid REFERENCES auth.users(id),
 reviewed_at timestamptz,
 reviewed_by uuid REFERENCES auth.users(id),
 resolution_note text,
 CHECK(reviewed_at IS NULL OR reviewed_by IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS jl_findings_org_status_idx ON public.jl_intelligence_findings(organisation_id,status,severity,created_at DESC);

CREATE TABLE IF NOT EXISTS public.jl_finding_review_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 finding_id uuid NOT NULL REFERENCES public.jl_intelligence_findings(id) ON DELETE RESTRICT,
 action text NOT NULL CHECK(action IN ('opened','assigned','commented','resolved','reopened','dismissed')),
 note text,
 actor_user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now()
);

-- Trial records live in their own domain and are not routine patient records.
CREATE TABLE IF NOT EXISTS public.jl_trial_studies (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 study_code text NOT NULL,
 title text NOT NULL,
 status text NOT NULL DEFAULT 'planning' CHECK(status IN ('planning','active','paused','closed')),
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 UNIQUE(organisation_id,study_code)
);
CREATE TABLE IF NOT EXISTS public.jl_trial_participants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organisation_id uuid NOT NULL REFERENCES public.jl_organisations(id) ON DELETE CASCADE,
 study_id uuid NOT NULL REFERENCES public.jl_trial_studies(id) ON DELETE CASCADE,
 participant_code text NOT NULL,
 status text NOT NULL DEFAULT 'screening' CHECK(status IN ('screening','enrolled','withdrawn','completed','screen_failed')),
 created_at timestamptz NOT NULL DEFAULT now(),
 created_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 UNIQUE(study_id,participant_code),
 UNIQUE(organisation_id,id)
);
CREATE INDEX IF NOT EXISTS jl_trial_participants_study_idx ON public.jl_trial_participants(organisation_id,study_id,status);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['jl_encounters','jl_source_observations','jl_intelligence_findings','jl_finding_review_events','jl_trial_studies','jl_trial_participants']
 LOOP EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t); EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t); END LOOP;
END $$;

-- Existing patient access policy is preserved; it uses the current org_id model.

DROP POLICY IF EXISTS jl_encounters_select ON public.jl_encounters;
CREATE POLICY jl_encounters_select ON public.jl_encounters FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer','read_only']::text[]));
DROP POLICY IF EXISTS jl_encounters_insert ON public.jl_encounters;
CREATE POLICY jl_encounters_insert ON public.jl_encounters FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory']::text[]) AND created_by=auth.uid());

DROP POLICY IF EXISTS jl_observations_select ON public.jl_source_observations;
CREATE POLICY jl_observations_select ON public.jl_source_observations FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer','read_only']::text[]));
DROP POLICY IF EXISTS jl_observations_insert ON public.jl_source_observations;
CREATE POLICY jl_observations_insert ON public.jl_source_observations FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics']::text[]) AND created_by=auth.uid());

DROP POLICY IF EXISTS jl_findings_select ON public.jl_intelligence_findings;
CREATE POLICY jl_findings_select ON public.jl_intelligence_findings FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer','read_only']::text[]));
DROP POLICY IF EXISTS jl_findings_insert ON public.jl_intelligence_findings;
CREATE POLICY jl_findings_insert ON public.jl_intelligence_findings FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics']::text[]) AND (created_by IS NULL OR created_by=auth.uid()));
DROP POLICY IF EXISTS jl_findings_update ON public.jl_intelligence_findings;
CREATE POLICY jl_findings_update ON public.jl_intelligence_findings FOR UPDATE TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer']::text[])) WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer']::text[]));

DROP POLICY IF EXISTS jl_finding_events_select ON public.jl_finding_review_events;
CREATE POLICY jl_finding_events_select ON public.jl_finding_review_events FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer','read_only']::text[]));
DROP POLICY IF EXISTS jl_finding_events_insert ON public.jl_finding_review_events;
CREATE POLICY jl_finding_events_insert ON public.jl_finding_review_events FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','hospital','laboratory','bioinformatics','reviewer']::text[]) AND actor_user_id=auth.uid());

DROP POLICY IF EXISTS jl_trial_studies_select ON public.jl_trial_studies;
CREATE POLICY jl_trial_studies_select ON public.jl_trial_studies FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial','reviewer','read_only']::text[]));
DROP POLICY IF EXISTS jl_trial_studies_insert ON public.jl_trial_studies;
CREATE POLICY jl_trial_studies_insert ON public.jl_trial_studies FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[]) AND created_by=auth.uid());
DROP POLICY IF EXISTS jl_trial_studies_update ON public.jl_trial_studies;
CREATE POLICY jl_trial_studies_update ON public.jl_trial_studies FOR UPDATE TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[])) WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[]));

DROP POLICY IF EXISTS jl_trial_participants_select ON public.jl_trial_participants;
CREATE POLICY jl_trial_participants_select ON public.jl_trial_participants FOR SELECT TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial','reviewer']::text[]));
DROP POLICY IF EXISTS jl_trial_participants_insert ON public.jl_trial_participants;
CREATE POLICY jl_trial_participants_insert ON public.jl_trial_participants FOR INSERT TO authenticated WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[]) AND created_by=auth.uid());
DROP POLICY IF EXISTS jl_trial_participants_update ON public.jl_trial_participants;
CREATE POLICY jl_trial_participants_update ON public.jl_trial_participants FOR UPDATE TO authenticated USING(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[])) WITH CHECK(public.jl_has_org_role(organisation_id,ARRAY['owner','org_admin','clinical_trial']::text[]));

CREATE OR REPLACE FUNCTION public.jl_validate_encounter_patient_org()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.jl_patients p WHERE p.id=NEW.patient_id AND p.org_id=NEW.organisation_id) THEN RAISE EXCEPTION 'Patient and encounter must belong to the same organisation'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS jl_encounter_patient_org_guard ON public.jl_encounters;
CREATE TRIGGER jl_encounter_patient_org_guard BEFORE INSERT OR UPDATE ON public.jl_encounters FOR EACH ROW EXECUTE FUNCTION public.jl_validate_encounter_patient_org();

CREATE OR REPLACE FUNCTION public.jl_validate_observation_links()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.jl_patients p WHERE p.id=NEW.patient_id AND p.org_id=NEW.organisation_id) THEN RAISE EXCEPTION 'Observation patient must belong to the same organisation'; END IF;
 IF NEW.encounter_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.jl_encounters e WHERE e.id=NEW.encounter_id AND e.organisation_id=NEW.organisation_id AND e.patient_id=NEW.patient_id) THEN RAISE EXCEPTION 'Observation encounter must match its patient and organisation'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS jl_observation_links_guard ON public.jl_source_observations;
CREATE TRIGGER jl_observation_links_guard BEFORE INSERT OR UPDATE ON public.jl_source_observations FOR EACH ROW EXECUTE FUNCTION public.jl_validate_observation_links();

CREATE OR REPLACE FUNCTION public.jl_validate_trial_participant_org()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.jl_trial_studies s WHERE s.id=NEW.study_id AND s.organisation_id=NEW.organisation_id) THEN RAISE EXCEPTION 'Trial participant must belong to the same organisation as the study'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS jl_trial_participant_org_guard ON public.jl_trial_participants;
CREATE TRIGGER jl_trial_participant_org_guard BEFORE INSERT OR UPDATE ON public.jl_trial_participants FOR EACH ROW EXECUTE FUNCTION public.jl_validate_trial_participant_org();

COMMIT;
