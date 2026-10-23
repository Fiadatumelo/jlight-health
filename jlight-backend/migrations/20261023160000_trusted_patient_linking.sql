-- Trusted cross-system patient identity crosswalk for the shared non-trial journey.
-- Raw source patient references are never stored; the API stores keyed HMAC digests only.
BEGIN;

CREATE TABLE IF NOT EXISTS jlight_canonical_patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jlight_canonical_patients_org_active
    ON jlight_canonical_patients (organization_id, id) WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS jlight_patient_link_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
    source_patient_ref_hash TEXT NOT NULL CHECK (source_patient_ref_hash ~ '^[0-9a-f]{64}$'),
    action TEXT NOT NULL CHECK (action IN ('link', 'unlink')),
    jlight_patient_id UUID,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    verified_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_values_modified BOOLEAN NOT NULL DEFAULT FALSE CHECK (source_values_modified = FALSE),
    CHECK ((action = 'link' AND jlight_patient_id IS NOT NULL)
        OR (action = 'unlink' AND jlight_patient_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_jlight_patient_link_lookup
    ON jlight_patient_link_events
       (organization_id, source_system, source_patient_ref_hash, created_at DESC, id DESC);

ALTER TABLE jlight_workflow_events
    ADD COLUMN IF NOT EXISTS source_patient_ref_hash TEXT
    CHECK (source_patient_ref_hash IS NULL OR source_patient_ref_hash ~ '^[0-9a-f]{64}$');
ALTER TABLE jlight_source_record_versions
    ADD COLUMN IF NOT EXISTS source_patient_ref_hash TEXT
    CHECK (source_patient_ref_hash IS NULL OR source_patient_ref_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE jlight_canonical_patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE jlight_patient_link_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS jlight_canonical_patient_select ON jlight_canonical_patients;
CREATE POLICY jlight_canonical_patient_select ON jlight_canonical_patients
    FOR SELECT USING (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);
DROP POLICY IF EXISTS jlight_canonical_patient_insert ON jlight_canonical_patients;
CREATE POLICY jlight_canonical_patient_insert ON jlight_canonical_patients
    FOR INSERT WITH CHECK (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);

DROP POLICY IF EXISTS jlight_patient_link_select ON jlight_patient_link_events;
CREATE POLICY jlight_patient_link_select ON jlight_patient_link_events
    FOR SELECT USING (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);
DROP POLICY IF EXISTS jlight_patient_link_insert ON jlight_patient_link_events;
CREATE POLICY jlight_patient_link_insert ON jlight_patient_link_events
    FOR INSERT WITH CHECK (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);

REVOKE ALL ON TABLE jlight_canonical_patients, jlight_patient_link_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE jlight_canonical_patients, jlight_patient_link_events TO jlight_runtime;
GRANT USAGE, SELECT ON SEQUENCE jlight_patient_link_events_id_seq TO jlight_runtime;

COMMIT;
