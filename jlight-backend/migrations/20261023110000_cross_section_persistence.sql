-- JLIGHT cross-section persistence foundation.
-- Apply only after provisioning PostgreSQL and confirming the application DB role.
-- Tenant isolation fails closed unless a trusted server-side caller sets
-- transaction-local jlight.organization_id. Never set it from an untrusted request field.

BEGIN;

CREATE TABLE IF NOT EXISTS jlight_source_record_versions (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
    source_record_id TEXT NOT NULL CHECK (length(trim(source_record_id)) > 0),
    domain TEXT NOT NULL CHECK (domain IN ('hospital', 'laboratory', 'bioinformatics')),
    record_type TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    jlight_patient_id TEXT,
    patient_link_verified BOOLEAN NOT NULL DEFAULT FALSE,
    link_status TEXT NOT NULL CHECK (link_status IN ('verified', 'unlinked', 'conflict_hold')),
    source_values_modified BOOLEAN NOT NULL DEFAULT FALSE CHECK (source_values_modified = FALSE),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, source_system, source_record_id, source_updated_at, payload_sha256),
    CHECK (
      (patient_link_verified = TRUE AND jlight_patient_id IS NOT NULL AND link_status = 'verified')
      OR
      (patient_link_verified = FALSE AND jlight_patient_id IS NULL AND link_status IN ('unlinked', 'conflict_hold'))
    )
);

CREATE INDEX IF NOT EXISTS idx_jlight_record_org_patient_time
    ON jlight_source_record_versions (organization_id, jlight_patient_id, source_updated_at DESC)
    WHERE patient_link_verified = TRUE;
CREATE INDEX IF NOT EXISTS idx_jlight_record_org_source
    ON jlight_source_record_versions (organization_id, source_system, source_record_id, source_updated_at DESC);

CREATE TABLE IF NOT EXISTS jlight_workflow_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL,
    event_id TEXT NOT NULL CHECK (length(trim(event_id)) > 0),
    source_system TEXT NOT NULL CHECK (length(trim(source_system)) > 0),
    source_record_id TEXT NOT NULL CHECK (length(trim(source_record_id)) > 0),
    domain TEXT NOT NULL CHECK (domain IN ('hospital', 'laboratory', 'bioinformatics')),
    event_type TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source_status TEXT,
    jlight_patient_id TEXT,
    patient_link_verified BOOLEAN NOT NULL DEFAULT FALSE,
    source_values_modified BOOLEAN NOT NULL DEFAULT FALSE CHECK (source_values_modified = FALSE),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, event_id),
    CHECK (
      (patient_link_verified = TRUE AND jlight_patient_id IS NOT NULL)
      OR
      (patient_link_verified = FALSE AND jlight_patient_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_jlight_events_org_source_time
    ON jlight_workflow_events (organization_id, source_system, source_record_id, observed_at, event_id);
CREATE INDEX IF NOT EXISTS idx_jlight_events_org_patient_time
    ON jlight_workflow_events (organization_id, jlight_patient_id, observed_at DESC)
    WHERE patient_link_verified = TRUE;

-- Fail-closed tenant boundary. A trusted server-side transaction must set this
-- using set_config(..., true) after authenticating the actor and resolving membership.
ALTER TABLE jlight_source_record_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE jlight_workflow_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS jlight_record_tenant_isolation ON jlight_source_record_versions;
CREATE POLICY jlight_record_tenant_isolation ON jlight_source_record_versions
    USING (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);

DROP POLICY IF EXISTS jlight_event_tenant_isolation ON jlight_workflow_events;
CREATE POLICY jlight_event_tenant_isolation ON jlight_workflow_events
    USING (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('jlight.organization_id', true), '')::uuid);

-- These are immutable evidence tables: app roles receive no UPDATE/DELETE policy.
-- Table owners and BYPASSRLS roles can bypass RLS; production deployment must use
-- a restricted non-owner runtime role and must not expose raw SQL to clients.

COMMIT;
