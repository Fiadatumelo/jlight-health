-- Tenant membership registry for authenticated JLIGHT API access.
-- Provision organization IDs and memberships through a trusted administrator process.
-- Never allow end users to self-assign membership or roles.
BEGIN;

CREATE TABLE IF NOT EXISTS jlight_organization_memberships (
    id BIGSERIAL PRIMARY KEY,
    auth_subject UUID NOT NULL,
    organization_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'clinician', 'laboratory', 'bioinformatics', 'viewer')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,
    UNIQUE (auth_subject, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_jlight_membership_subject_active
    ON jlight_organization_memberships (auth_subject, organization_id)
    WHERE active = TRUE;

ALTER TABLE jlight_organization_memberships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS jlight_membership_select_self ON jlight_organization_memberships;
CREATE POLICY jlight_membership_select_self ON jlight_organization_memberships
    FOR SELECT
    USING (auth_subject = NULLIF(current_setting('jlight.auth_subject', true), '')::uuid);

-- Memberships are provisioned by a trusted administrative process, not client APIs.
REVOKE ALL ON TABLE jlight_organization_memberships FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE jlight_organization_memberships TO jlight_runtime;
REVOKE ALL ON SEQUENCE jlight_organization_memberships_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE jlight_organization_memberships_id_seq TO jlight_runtime;
COMMIT;
