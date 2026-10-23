-- Durable tenant-isolated retry queue for read-only source exports.
BEGIN;
CREATE TABLE IF NOT EXISTS jlight_ingestion_queue (
 id BIGSERIAL PRIMARY KEY,
 organization_id UUID NOT NULL,
 idempotency_key TEXT NOT NULL CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 200),
 source_system TEXT NOT NULL CHECK (length(trim(source_system)) BETWEEN 1 AND 200),
 domain TEXT NOT NULL CHECK (domain IN ('hospital','laboratory','bioinformatics')),
 export_format TEXT NOT NULL CHECK (export_format IN ('fhir','hl7v2','csv')),
 payload JSONB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','retry','completed','dead_letter')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
 max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
 available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 lease_token UUID,
 lease_expires_at TIMESTAMPTZ,
 last_error_code TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 completed_at TIMESTAMPTZ,
 UNIQUE (organization_id,idempotency_key),
 CHECK ((status='processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status<>'processing' AND lease_token IS NULL AND lease_expires_at IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_jlight_queue_claim ON jlight_ingestion_queue (organization_id,status,available_at,created_at) WHERE status IN ('pending','retry','processing');
CREATE INDEX IF NOT EXISTS idx_jlight_queue_dead_letter ON jlight_ingestion_queue (organization_id,updated_at DESC) WHERE status='dead_letter';
ALTER TABLE jlight_ingestion_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS jlight_queue_tenant_select ON jlight_ingestion_queue;
CREATE POLICY jlight_queue_tenant_select ON jlight_ingestion_queue FOR SELECT USING (organization_id=NULLIF(current_setting('jlight.organization_id',true),'')::uuid);
DROP POLICY IF EXISTS jlight_queue_tenant_insert ON jlight_ingestion_queue;
CREATE POLICY jlight_queue_tenant_insert ON jlight_ingestion_queue FOR INSERT WITH CHECK (organization_id=NULLIF(current_setting('jlight.organization_id',true),'')::uuid);
DROP POLICY IF EXISTS jlight_queue_tenant_update ON jlight_ingestion_queue;
CREATE POLICY jlight_queue_tenant_update ON jlight_ingestion_queue FOR UPDATE USING (organization_id=NULLIF(current_setting('jlight.organization_id',true),'')::uuid) WITH CHECK (organization_id=NULLIF(current_setting('jlight.organization_id',true),'')::uuid);
REVOKE ALL ON TABLE jlight_ingestion_queue FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON TABLE jlight_ingestion_queue TO jlight_runtime;
GRANT USAGE,SELECT ON SEQUENCE jlight_ingestion_queue_id_seq TO jlight_runtime;
COMMIT;
