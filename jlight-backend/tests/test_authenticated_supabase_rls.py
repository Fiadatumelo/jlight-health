"""Authenticated Supabase RLS integration gates.

Run only against a disposable Supabase staging database. Fixtures stay inside one
outer transaction and are rolled back at class teardown. Never use production.
"""
import csv
import json
import os
import unittest
import uuid
from pathlib import Path

try:
    import psycopg2
except ImportError:  # Keep the ordinary unit-test suite usable without integration deps.
    psycopg2 = None


STAGING_DSN = os.getenv("JLIGHT_STAGING_DATABASE_URL", "")
STAGING_REF = os.getenv("JLIGHT_STAGING_PROJECT_REF", "")
EXPECTED_STAGING_REF = "ampkysrzliwjtvbigsvu"


@unittest.skipUnless(STAGING_DSN and psycopg2, "staging database credentials are not configured")
class AuthenticatedSupabaseRLSGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if STAGING_REF != EXPECTED_STAGING_REF or EXPECTED_STAGING_REF not in STAGING_DSN:
            raise RuntimeError("Refusing RLS integration tests unless the database URL matches the verified staging project")
        cls.conn = psycopg2.connect(STAGING_DSN)
        cls.conn.autocommit = False
        # Fixtures create disposable auth.users rows inside a rollback-only
        # transaction. The CI secret must therefore be the staging database
        # administrator connection, never an anon/authenticated application URL.
        with cls.conn.cursor() as cursor:
            cursor.execute(
                """SELECT current_user, r.rolsuper,
                          has_table_privilege(current_user, 'auth.users', 'INSERT')
                   FROM pg_roles r WHERE r.rolname = current_user"""
            )
            db_user, is_superuser, can_seed_auth = cursor.fetchone()
        if not is_superuser and not can_seed_auth:
            cls.conn.close()
            raise RuntimeError(
                "JLIGHT_STAGING_DATABASE_URL must use a staging database administrator "
                "that can create rollback-only synthetic auth.users fixtures; "
                f"connected role {db_user!r} cannot seed auth.users. Do not weaken RLS."
            )
        cls.a = str(uuid.uuid4())
        cls.b = str(uuid.uuid4())
        cls.platform_admin = str(uuid.uuid4())
        cls.hospital_only = str(uuid.uuid4())
        cls.org_code_only = str(uuid.uuid4())
        cls.new_registrant = str(uuid.uuid4())
        cls.invited_target = str(uuid.uuid4())
        cls.org_a = str(uuid.uuid4())
        cls.org_b = str(uuid.uuid4())
        cls.trial_org = str(uuid.uuid4())
        cls.patient_a = str(uuid.uuid4())
        cls.patient_b = str(uuid.uuid4())
        cls.encounter_a = str(uuid.uuid4())
        cls.encounter_b = str(uuid.uuid4())
        cls.finding_a = str(uuid.uuid4())
        cls.finding_b = str(uuid.uuid4())
        cls.event_a = str(uuid.uuid4())
        cls.event_b = str(uuid.uuid4())
        cls.study = str(uuid.uuid4())
        cls.bio_accession = str(uuid.uuid4())
        cls.bio_run = str(uuid.uuid4())
        cls.bio_qc = str(uuid.uuid4())
        cls.bio_amr = str(uuid.uuid4())
        cls.participant = str(uuid.uuid4())
        cls._seed_transactional_fixtures()

    @classmethod
    def _seed_transactional_fixtures(cls):
        c = cls.conn.cursor()
        # Database URL is pinned to the verified staging project before connecting.
        for uid, email in ((cls.a, "rls-a@invalid.example"), (cls.b, "rls-b@invalid.example"),
                          (cls.platform_admin, "rls-platform-admin@invalid.example"),
                          (cls.hospital_only, "rls-hospital-only@invalid.example"),
                          (cls.org_code_only, "rls-org-code-only@invalid.example"),
                          (cls.new_registrant, "rls-new-registrant@invalid.example"),
                          (cls.invited_target, "rls-invited-target@invalid.example")):
            c.execute(
                """INSERT INTO auth.users
                   (id, aud, role, email, encrypted_password, email_confirmed_at,
                    raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
                   VALUES (%s, 'authenticated', 'authenticated', %s, '', now(),
                           '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now())""",
                (uid, email),
            )
        c.execute(
            """INSERT INTO public.jl_platform_admins (user_id, admin_role, active, created_by)
               VALUES (%s, 'platform_super_admin', true, %s)""",
            (cls.platform_admin, cls.platform_admin),
        )
        # Owner-membership seed triggers create the corresponding membership records.
        for org_id, name, email, uid, role, workspace_type in (
            (cls.org_a, "RLS synthetic hospital A", "rls-a@invalid.example", cls.a, "Hospital", "hospital"),
            (cls.org_b, "RLS synthetic hospital B", "rls-b@invalid.example", cls.b, "Hospital", "hospital"),
            (cls.trial_org, "RLS synthetic trial", "rls-a@invalid.example", cls.a, "Trial", "clinical_trials"),
        ):
            c.execute(
                """INSERT INTO public.jl_organisations
                   (id, name, role, owner_email, owner_user_id, type)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (org_id, name, role, email, uid, workspace_type),
            )
        c.execute("SELECT org_code FROM public.jl_organisations WHERE id=%s", (cls.org_a,))
        cls.org_a_code = c.fetchone()[0]
        # Seed active organisation-level entitlements before member permissions.
        for org_id, domains in (
            (cls.org_a, ("hospital", "laboratory", "bioinformatics")),
            (cls.org_b, ("hospital", "laboratory", "bioinformatics")),
            (cls.trial_org, ("clinical_trials",)),
        ):
            for domain in domains:
                c.execute(
                    """INSERT INTO public.jl_organisation_workspaces
                       (org_id, workspace_key, status, provisioning_source, approved_at)
                       VALUES (%s, %s, 'active', 'legacy_backfill', now())
                       ON CONFLICT (org_id, workspace_key) DO NOTHING""",
                    (org_id, domain),
                )
        # Ensure the newer membership model exists for the two hospital users.
        # The legacy trigger may intentionally skip mapping depending on org role/type.
        c.execute(
            """INSERT INTO public.jlight_organization_memberships
               (organization_id, auth_subject, role, active, created_by)
               VALUES (%s, %s, 'owner', true, %s),
                      (%s, %s, 'owner', true, %s),
                      (%s, %s, 'clinician', true, %s)
               ON CONFLICT (organization_id, auth_subject)
               DO UPDATE SET role = EXCLUDED.role, active = true""",
            (cls.org_a, cls.a, cls.a, cls.org_b, cls.b, cls.b, cls.org_a, cls.hospital_only, cls.a),
        )
        # The patients_org policy additionally requires a current organisation
        # in jl_user_profiles; use one active profile per synthetic user.
        for uid, org_id in ((cls.a, cls.org_a), (cls.b, cls.org_b), (cls.hospital_only, cls.org_a)):
            c.execute(
                """INSERT INTO public.jl_user_profiles
                   (user_id, org_id, full_name, workspace_role, active)
                   VALUES (%s, %s, %s, 'operator', true)""",
                (uid, org_id, "Synthetic RLS user"),
            )
        for org_id, uid in ((cls.org_a, cls.a), (cls.org_b, cls.b)):
            for domain in ("hospital", "laboratory", "bioinformatics"):
                c.execute(
                    """INSERT INTO public.jlight_membership_domain_permissions
                       (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
                       VALUES (%s, %s, %s, true, true, true, %s)
                       ON CONFLICT (organization_id, auth_subject, domain)
                       DO UPDATE SET can_read = EXCLUDED.can_read,
                                     can_write = EXCLUDED.can_write,
                                     can_report = EXCLUDED.can_report""",
                    (org_id, uid, domain, uid),
                )
        # This member belongs to the same organisation but has Hospital permission only.
        c.execute(
            """INSERT INTO public.jlight_membership_domain_permissions
               (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
               VALUES (%s, %s, 'hospital', true, true, true, %s)
               ON CONFLICT (organization_id, auth_subject, domain)
               DO UPDATE SET can_read=true, can_write=true, can_report=true""",
            (cls.org_a, cls.hospital_only, cls.a),
        )
        # Seed normalized Bioinformatics rows with synthetic data and no patient link.
        c.execute(
            """INSERT INTO public.jl_bio_accessions
               (id, org_id, accession_no, sample_type, created_at)
               VALUES (%s, %s, 'SYNTH-BIO-ACCESSION', 'WGS', now())""",
            (cls.bio_accession, cls.org_a),
        )
        c.execute(
            """INSERT INTO public.jl_bio_runs
               (id, org_id, accession_id, run_id, analysis_type, platform,
                reference_genome, pipeline, pipeline_version, stage, submitted_at, created_at)
               VALUES (%s, %s, %s, 'SYNTH-TB-RUN-001', 'WGS-TB-Profiler', 'Illumina',
                       'H37Rv', 'TBProfiler', '6.7.0', 'completed', now(), now())""",
            (cls.bio_run, cls.org_a, cls.bio_accession),
        )
        c.execute(
            """INSERT INTO public.jl_bio_qc
               (id, org_id, run_id, coverage_mean, mapping_rate, q_score, dup_rate,
                gc_content, contamination, qc_status, created_at)
               VALUES (%s, %s, %s, 45.0, 0.99, 35.0, 0.05, 65.0, 0.01, 'pass', now())""",
            (cls.bio_qc, cls.org_a, cls.bio_run),
        )
        c.execute(
            """INSERT INTO public.jl_bio_amr
               (id, org_id, run_id, gene, antibiotic_class, resistance_level,
                confidence, database_version, created_at)
               VALUES (%s, %s, %s, 'rpoB', 'rifamycin', 'associated',
                       0.99, 'WHOv2+', now())""",
            (cls.bio_amr, cls.org_a, cls.bio_run),
        )

        # Load the public TBProfiler CSV fixture through the same bioRuns payload
        # contract used by the JLIGHT source importer. It contains no patient link.
        fixture = Path(__file__).resolve().parents[2] / "validation" / "tbprofiler" / "fixtures" / "public_tbprofiler_bioruns.csv"
        with fixture.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                c.execute(
                    """INSERT INTO public.jl_entries
                       (id, jl_id, user_id, organisation, role, ts, payload, created_at, org_id, domain)
                       VALUES (%s, %s, %s, 'RLS Org A', 'Bioinformatics', %s, %s::jsonb, %s, %s, 'bioRuns')""",
                    (
                        str(uuid.uuid4()),
                        "TBP-" + row["sourceRecordId"],
                        cls.a,
                        row["createdAt"],
                        json.dumps(row),
                        row["createdAt"],
                        cls.org_a,
                    ),
                )

        # Trial organisation is intentionally not added to the hospital-domain membership model.
        c.execute(
            """INSERT INTO public.jl_patients (id, org_id, mrn, full_name)
               VALUES (%s, %s, 'PATION-001', 'PATION-001'), (%s, %s, 'PATION-001', 'PATION-001')""",
            (cls.patient_a, cls.org_a, cls.patient_b, cls.org_b),
        )
        for enc_id, org_id, patient_id, uid, ref in (
            (cls.encounter_a, cls.org_a, cls.patient_a, cls.a, "SYNTH-A"),
            (cls.encounter_b, cls.org_b, cls.patient_b, cls.b, "SYNTH-B"),
        ):
            c.execute(
                """INSERT INTO public.jl_encounters
                   (id, organisation_id, patient_id, source_system, source_encounter_ref,
                    encounter_type, occurred_at, status, created_by)
                   VALUES (%s, %s, %s, 'SYNTHETIC', %s, 'hospital', now(), 'open', %s)""",
                (enc_id, org_id, patient_id, ref, uid),
            )
        for finding_id, org_id, patient_id, uid, title in (
            (cls.finding_a, cls.org_a, cls.patient_a, cls.a, "Synthetic finding A"),
            (cls.finding_b, cls.org_b, cls.patient_b, cls.b, "Synthetic finding B"),
        ):
            c.execute(
                """INSERT INTO public.jl_intelligence_findings
                   (id, organisation_id, patient_id, finding_type, severity, status, title,
                    explanation, rule_version, created_by, reviewed_at, reviewed_by)
                   VALUES (%s, %s, %s, 'synthetic_validation', 'low', 'resolved', %s,
                           'Rollback-only synthetic RLS fixture', 'test-v1', %s, now(), %s)""",
                (finding_id, org_id, patient_id, title, uid, uid),
            )
        for event_id, org_id, finding_id, uid in (
            (cls.event_a, cls.org_a, cls.finding_a, cls.a),
            (cls.event_b, cls.org_b, cls.finding_b, cls.b),
        ):
            # Review-event trigger enforces that actor_user_id matches auth.uid().
            c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (uid,))
            c.execute(
                """INSERT INTO public.jl_finding_review_events
                   (id, organisation_id, finding_id, action, note, actor_user_id)
                   VALUES (%s, %s, %s, 'resolved', 'Rollback-only synthetic event', %s)""",
                (event_id, org_id, finding_id, uid),
            )
        c.execute(
            """INSERT INTO public.jl_trial_studies
               (id, organisation_id, study_code, title, status, created_by)
               VALUES (%s, %s, 'RLS-SYNTH-TRIAL', 'Synthetic trial isolation', 'active', %s)""",
            (cls.study, cls.trial_org, cls.a),
        )
        c.execute(
            """INSERT INTO public.jl_trial_participants
               (id, organisation_id, study_id, participant_code, status, created_by)
               VALUES (%s, %s, %s, 'PATION-TRIAL-001', 'enrolled', %s)""",
            (cls.participant, cls.trial_org, cls.study, cls.a),
        )

    def _as_user(self, uid):
        c = self.conn.cursor()
        c.execute("SAVEPOINT rls_test")
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (uid,))
        return c

    def test_patient_matching_is_exact_and_organisation_scoped(self):
        c = self._as_user(self.a)
        c.execute("SELECT id FROM public.jl_patients WHERE mrn = 'PATION-001'")
        self.assertEqual([row[0] for row in c.fetchall()], [self.patient_a])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_cross_organisation_encounters_and_findings_are_hidden(self):
        c = self._as_user(self.a)
        c.execute("SELECT id FROM public.jl_encounters")
        self.assertEqual([row[0] for row in c.fetchall()], [self.encounter_a])
        c.execute("SELECT id FROM public.jl_intelligence_findings")
        self.assertEqual([row[0] for row in c.fetchall()], [self.finding_a])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_issue_resolution_history_is_tenant_scoped(self):
        c = self._as_user(self.a)
        c.execute("SELECT id, finding_id FROM public.jl_finding_review_events")
        self.assertEqual(c.fetchall(), [(self.event_a, self.finding_a)])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_report_permission_allows_owner_and_denies_other_organisation(self):
        c = self._as_user(self.a)
        c.execute(
            "SELECT public.jlight_has_domain_permission(%s, 'bioinformatics', 'report')",
            (self.org_a,),
        )
        self.assertTrue(c.fetchone()[0])
        c.execute(
            "SELECT public.jlight_has_domain_permission(%s, 'bioinformatics', 'report')",
            (self.org_b,),
        )
        self.assertFalse(c.fetchone()[0])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_initial_registration_creates_one_org_with_only_selected_workspaces(self):
        c = self._as_user(self.new_registrant)
        c.execute(
            "SELECT public.jl_register_organisation_multi(%s, %s)",
            ("RLS Multi-Path Registration", ["hospital", "laboratory"]),
        )
        registration = c.fetchone()[0]
        self.assertTrue(registration["id"])
        self.assertTrue(registration["org_code"])
        self.assertEqual(set(registration["workspace_keys"]), {"hospital", "laboratory"})

        c.execute("SELECT public.jl_list_my_workspaces(%s)", (registration["id"],))
        visible = c.fetchone()[0]
        self.assertEqual(
            {item["key"] for item in visible[0]["workspaces"]},
            {"hospital", "laboratory"},
        )

        c.execute("SAVEPOINT duplicate_registration")
        with self.assertRaises(psycopg2.errors.UniqueViolation):
            c.execute(
                "SELECT public.jl_register_organisation_multi(%s, %s)",
                ("Second Organisation Attempt", ["bioinformatics"]),
            )
        c.execute("ROLLBACK TO SAVEPOINT duplicate_registration")
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_organisation_code_alone_does_not_grant_membership(self):
        c = self._as_user(self.org_code_only)
        c.execute("SAVEPOINT code_only_link")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                "SELECT public.jl_link_user_to_organisation(%s, %s, %s, %s)",
                (self.org_a, self.org_a_code, "Uninvited user", "operator"),
            )
        c.execute("ROLLBACK TO SAVEPOINT code_only_link")

        c.execute("SAVEPOINT code_only_invitation")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                "SELECT public.jl_accept_organisation_invitation(%s, %s)",
                (self.org_a, self.org_a_code),
            )
        c.execute("ROLLBACK TO SAVEPOINT code_only_invitation")
        c.execute("SELECT public.jl_list_my_workspaces(NULL)")
        self.assertEqual(c.fetchone()[0], [])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_public_tbprofiler_import_records_are_workspace_and_tenant_scoped(self):
        c = self._as_user(self.a)
        c.execute(
            """SELECT jl_id, payload FROM public.jl_entries
               WHERE domain='bioRuns' AND jl_id LIKE 'TBP-%' ORDER BY jl_id"""
        )
        rows = c.fetchall()
        self.assertEqual(len(rows), 2)
        summaries = {
            row[1]["sourceRecordId"]: json.loads(row[1]["summary"])
            for row in rows
        }
        self.assertEqual(summaries["ERR10610053"]["drugResistanceCall"], "Pre-XDR-TB")
        self.assertEqual(summaries["ERR10610053"]["medianCoverage"], 48.0)
        self.assertEqual(summaries["ERR10610083"]["medianCoverage"], 12.0)
        self.assertTrue(summaries["ERR10610083"]["qcWarnings"])
        self.assertNotIn("patientId", summaries["ERR10610053"])

        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.hospital_only,))
        c.execute(
            "SELECT jl_id FROM public.jl_entries WHERE domain='bioRuns' AND jl_id LIKE 'TBP-%'"
        )
        self.assertEqual(c.fetchall(), [])

        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.b,))
        c.execute(
            "SELECT jl_id FROM public.jl_entries WHERE domain='bioRuns' AND jl_id LIKE 'TBP-%'"
        )
        self.assertEqual(c.fetchall(), [])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_bioinformatics_tables_require_bioinformatics_workspace_permission(self):
        c = self._as_user(self.a)
        c.execute("SELECT id FROM public.jl_bio_accessions WHERE org_id=%s", (self.org_a,))
        self.assertEqual([row[0] for row in c.fetchall()], [self.bio_accession])
        c.execute("SELECT id FROM public.jl_bio_runs WHERE org_id=%s", (self.org_a,))
        self.assertEqual([row[0] for row in c.fetchall()], [self.bio_run])
        c.execute("SELECT id FROM public.jl_bio_qc WHERE org_id=%s", (self.org_a,))
        self.assertEqual([row[0] for row in c.fetchall()], [self.bio_qc])
        c.execute("SELECT id FROM public.jl_bio_amr WHERE org_id=%s", (self.org_a,))
        self.assertEqual([row[0] for row in c.fetchall()], [self.bio_amr])

        # A Hospital-only member in the same organisation must see none of these
        # records and must not be able to insert a Bioinformatics run.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.hospital_only,))
        for table in ("jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"):
            c.execute("SELECT id FROM public." + table)
            self.assertEqual(c.fetchall(), [], "Hospital-only member could read " + table)
        c.execute("SAVEPOINT bio_write_denial")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                """INSERT INTO public.jl_bio_runs
                   (id, org_id, run_id, analysis_type, stage, submitted_at, created_at)
                   VALUES (%s, %s, 'FORBIDDEN-HOSPITAL-RUN', 'WGS', 'completed', now(), now())""",
                (str(uuid.uuid4()), self.org_a),
            )
        c.execute("ROLLBACK TO SAVEPOINT bio_write_denial")

        # A Bioinformatics member in another organisation is still tenant-isolated.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.b,))
        for table in ("jl_bio_accessions", "jl_bio_runs", "jl_bio_qc", "jl_bio_amr"):
            c.execute("SELECT id FROM public." + table)
            self.assertEqual(c.fetchall(), [], "Cross-organisation Bioinformatics read leaked from " + table)

        # The Bioinformatics owner can write a new normalized run record.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute(
            """INSERT INTO public.jl_bio_runs
               (id, org_id, run_id, analysis_type, stage, submitted_at, created_at)
               VALUES (%s, %s, 'SYNTH-TB-RUN-WRITE', 'WGS-TB-Profiler', 'completed', now(), now())""",
            (str(uuid.uuid4()), self.org_a),
        )
        self.assertEqual(c.rowcount, 1)
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_laboratory_code_resolution_requires_entitlement_and_member_permission(self):
        c = self.conn.cursor()
        c.execute("SELECT org_code FROM public.jl_organisations WHERE id = %s", (self.org_a,))
        org_code = c.fetchone()[0]
        c.execute("SAVEPOINT lab_code_resolution_test")
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.b,))
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute("SELECT public.jl_resolve_lab_org(%s)", (org_code,))
        c.execute("ROLLBACK TO SAVEPOINT lab_code_resolution_test")
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute("SELECT public.jl_resolve_lab_org(%s)", (org_code,))
        self.assertEqual(str(c.fetchone()[0]), self.org_a)
        c.execute("ROLLBACK TO SAVEPOINT lab_code_resolution_test")
        c.execute("RELEASE SAVEPOINT lab_code_resolution_test")

    def test_platform_admin_cannot_authorise_recruitment_for_own_organisation(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT independent_recruitment_approval_test")
        c.execute(
            """INSERT INTO public.jl_org_memberships
               (organisation_id, user_id, access_role, status, created_by)
               VALUES (%s, %s, 'org_admin', 'active', %s)
               ON CONFLICT DO NOTHING""",
            (self.trial_org, self.platform_admin, self.a),
        )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute(
            "SELECT set_config('request.jwt.claim.sub', %s, true)",
            (self.platform_admin,),
        )
        with self.assertRaises(Exception):
            c.execute(
                """SELECT public.jl_authorise_trial_recruitment(
                     %s, 'SYNTH-ETHICS-APPROVAL', current_date, 'ct-criteria-test-v1')""",
                (self.study,),
            )
        c.execute("ROLLBACK TO SAVEPOINT independent_recruitment_approval_test")
        c.execute("RELEASE SAVEPOINT independent_recruitment_approval_test")

    def test_independent_platform_admin_can_authorise_other_organisation_recruitment(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT independent_recruitment_approval_positive_test")
        c.execute(
            """INSERT INTO public.jl_organisation_workspaces
               (org_id, workspace_key, status, provisioning_source, approved_at)
               VALUES (%s, 'clinical_trials', 'active', 'initial_registration', now())
               ON CONFLICT (org_id, workspace_key) DO UPDATE SET status='active'""",
            (self.org_b,),
        )
        study_id = str(uuid.uuid4())
        c.execute(
            """INSERT INTO public.jl_trial_studies
               (id, organisation_id, study_code, title, status, created_by)
               VALUES (%s, %s, %s, 'Independent approval synthetic study', 'active', %s)""",
            (study_id, self.org_b, "RLS-ADMIN-APPROVAL-" + study_id[:8], self.b),
        )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute(
            "SELECT set_config('request.jwt.claim.sub', %s, true)",
            (self.platform_admin,),
        )
        c.execute(
            """SELECT public.jl_authorise_trial_recruitment(
                 %s, 'SYNTH-ETHICS-APPROVAL', current_date, 'ct-criteria-test-v1')""",
            (study_id,),
        )
        c.execute("ROLLBACK TO SAVEPOINT independent_recruitment_approval_positive_test")
        c.execute("RELEASE SAVEPOINT independent_recruitment_approval_positive_test")

    def test_platform_admin_cannot_authorise_recruitment_for_non_active_study(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT inactive_study_recruitment_approval_test")
        c.execute(
            """INSERT INTO public.jl_organisation_workspaces
               (org_id, workspace_key, status, provisioning_source, approved_at)
               VALUES (%s, 'clinical_trials', 'active', 'initial_registration', now())
               ON CONFLICT (org_id, workspace_key) DO UPDATE SET status='active'""",
            (self.org_b,),
        )
        study_id = str(uuid.uuid4())
        c.execute(
            """INSERT INTO public.jl_trial_studies
               (id, organisation_id, study_code, title, status, created_by)
               VALUES (%s, %s, %s, 'Inactive synthetic study', 'planning', %s)""",
            (study_id, self.org_b, "RLS-PLANNING-STUDY-" + study_id[:8], self.b),
        )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute(
            "SELECT set_config('request.jwt.claim.sub', %s, true)",
            (self.platform_admin,),
        )
        with self.assertRaises(Exception):
            c.execute(
                """SELECT public.jl_authorise_trial_recruitment(
                     %s, 'SYNTH-ETHICS-APPROVAL', current_date, 'ct-criteria-test-v1')""",
                (study_id,),
            )
        c.execute("ROLLBACK TO SAVEPOINT inactive_study_recruitment_approval_test")
        c.execute("RELEASE SAVEPOINT inactive_study_recruitment_approval_test")

    def test_hospital_member_without_trial_read_cannot_create_recruitment_referral(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT referral_ct_read_permission_test")
        c.execute(
            """INSERT INTO public.jl_organisation_workspaces
               (org_id, workspace_key, status, provisioning_source, approved_at)
               VALUES (%s, 'clinical_trials', 'active', 'legacy_backfill', now())
               ON CONFLICT (org_id, workspace_key) DO UPDATE SET status='active'""",
            (self.org_a,),
        )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute(
            "SELECT set_config('request.jwt.claim.sub', %s, true)",
            (self.hospital_only,),
        )
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                """SELECT public.jl_create_trial_recruitment_referral(
                     %s, %s, %s, 'RLS-REFERRAL-NO-TRIAL-READ', '{}'::jsonb, 'ct-criteria-test-v1')""",
                (self.org_a, str(uuid.uuid4()), self.patient_a),
            )
        c.execute("ROLLBACK TO SAVEPOINT referral_ct_read_permission_test")
        c.execute("RELEASE SAVEPOINT referral_ct_read_permission_test")

    def test_clinical_trials_records_are_not_visible_from_hospital_membership(self):
        c = self._as_user(self.b)
        c.execute("SELECT id FROM public.jl_trial_studies")
        self.assertEqual(c.fetchall(), [])
        c.execute("SELECT id FROM public.jl_trial_participants")
        self.assertEqual(c.fetchall(), [])
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_workspace_entitlements_and_clinical_trials_membership_are_separate(self):
        c = self._as_user(self.a)
        c.execute(
            """SELECT
                 public.jlight_has_domain_permission(%s, 'hospital', 'read'),
                 public.jlight_has_domain_permission(%s, 'clinical_trials', 'read'),
                 public.jlight_has_domain_permission(%s, 'clinical_trials', 'read')""",
            (self.org_a, self.org_a, self.trial_org),
        )
        self.assertEqual(c.fetchone(), (True, False, True))
        c.execute("ROLLBACK TO SAVEPOINT rls_test")
        c.execute("RELEASE SAVEPOINT rls_test")

    def test_platform_admin_approval_is_required_for_additional_workspace(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT workspace_approval_test")
        owner = str(uuid.uuid4())
        c.execute(
            """INSERT INTO auth.users
               (id, aud, role, email, encrypted_password, email_confirmed_at,
                raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
               VALUES (%s, 'authenticated', 'authenticated', %s, '', now(),
                       '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now())""",
            (owner, "multi-path-owner-" + owner[:8] + "@invalid.example"),
        )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (owner,))
        c.execute(
            "SELECT public.jl_register_organisation_multi(%s, %s)",
            ("Synthetic multi-path RLS test", ["hospital", "bioinformatics", "clinical_trials"]),
        )
        organisation = c.fetchone()[0]
        org_id = organisation["id"]
        c.execute(
            """SELECT public.jl_request_additional_workspace(
                 %s, 'laboratory', %s, '2026-10-v1')""",
            (org_id, "secure://synthetic-evidence/" + owner),
        )
        request_id = c.fetchone()[0]
        c.execute(
            "SELECT public.jlight_has_domain_permission(%s, 'laboratory', 'read')",
            (org_id,),
        )
        self.assertFalse(c.fetchone()[0])

        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.platform_admin,))
        c.execute("SELECT public.jl_is_platform_super_admin()")
        self.assertTrue(c.fetchone()[0])
        c.execute(
            """SELECT public.jl_review_workspace_access_request(
                 %s, 'approved', 'Synthetic eligibility criteria verified')""",
            (request_id,),
        )
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (owner,))
        c.execute(
            "SELECT public.jlight_has_domain_permission(%s, 'laboratory', 'read')",
            (org_id,),
        )
        self.assertTrue(c.fetchone()[0])
        c.execute("ROLLBACK TO SAVEPOINT workspace_approval_test")
        c.execute("RELEASE SAVEPOINT workspace_approval_test")

    def test_scoped_invitation_grants_only_the_invited_workspace(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT scoped_invitation_test")
        target = self.invited_target
        c.execute("SELECT org_code FROM public.jl_organisations WHERE id = %s", (self.org_a,))
        org_code = c.fetchone()[0]
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute(
            "SELECT public.jl_invite_org_member(%s, 'bioinformatics')",
            ("rls-invited-target@invalid.example",),
        )
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (target,))
        c.execute(
            "SELECT public.jl_accept_organisation_invitation(%s, %s)",
            (self.org_a, org_code),
        )
        self.assertTrue(c.fetchone()[0])
        c.execute(
            "SELECT public.jl_link_user_to_organisation(%s, %s, NULL, 'operator')",
            (self.org_a, org_code),
        )
        c.execute(
            """SELECT
                 public.jlight_has_domain_permission(%s, 'bioinformatics', 'read'),
                 public.jlight_has_domain_permission(%s, 'hospital', 'read'),
                 public.jlight_has_domain_permission(%s, 'clinical_trials', 'read')""",
            (self.org_a, self.org_a, self.org_a),
        )
        self.assertEqual(c.fetchone(), (True, False, False))
        c.execute("ROLLBACK TO SAVEPOINT scoped_invitation_test")
        c.execute("RELEASE SAVEPOINT scoped_invitation_test")

    def test_governed_hospital_to_trial_recruitment_and_participant_lifecycle(self):
        c = self.conn.cursor()
        c.execute("SAVEPOINT governed_trial_recruitment_test")
        # This organisation has a Hospital workspace already. Activate the separate
        # Clinical Trials entitlement and add a distinct Trial member.
        c.execute(
            """INSERT INTO public.jl_organisation_workspaces
               (org_id, workspace_key, status, provisioning_source, approved_at)
               VALUES (%s, 'clinical_trials', 'active', 'legacy_backfill', now())
               ON CONFLICT (org_id, workspace_key)
               DO UPDATE SET status='active'""",
            (self.org_a,),
        )
        c.execute(
            """INSERT INTO public.jl_org_memberships
               (organisation_id, user_id, access_role, status, created_by)
               VALUES (%s, %s, 'clinical_trial', 'active', %s)
               ON CONFLICT (organisation_id, user_id, access_role)
               DO UPDATE SET status='active'""",
            (self.org_a, self.b, self.a),
        )
        c.execute(
            """INSERT INTO public.jlight_organization_memberships
               (organization_id, auth_subject, role, active, created_by)
               VALUES (%s, %s, 'clinician', true, %s)
               ON CONFLICT (organization_id, auth_subject)
               DO UPDATE SET role='clinician', active=true""",
            (self.org_a, self.b, self.a),
        )
        study_id = str(uuid.uuid4())
        c.execute(
            """INSERT INTO public.jl_trial_studies
               (id, organisation_id, study_code, title, status, created_by)
               VALUES (%s, %s, %s, 'Synthetic authorised recruitment study', 'active', %s)""",
            (study_id, self.org_a, 'RLS-RECRUIT-' + study_id[:8], self.a),
        )

        # The approval queue is platform-admin-only; the study is still pending.
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute("SAVEPOINT trial_approval_queue_denial")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM public.jl_list_trial_recruitment_approval_queue()")
        c.execute("ROLLBACK TO SAVEPOINT trial_approval_queue_denial")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.platform_admin,))
        c.execute("SELECT study_id FROM public.jl_list_trial_recruitment_approval_queue() WHERE study_id=%s", (study_id,))
        self.assertEqual(str(c.fetchone()[0]), study_id)

        # Only the independent platform administrator can enable recruitment.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.platform_admin,))
        c.execute(
            """SELECT public.jl_authorise_trial_recruitment(
                 %s, 'SYNTHETIC-ETHICS-APPROVAL', current_date, 'criteria-v1')""",
            (study_id,),
        )

        # Hospital owner submits a minimum-necessary referral. The hospital patient
        # identifier is written only to the private identity map.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute(
            """SELECT public.jl_create_trial_recruitment_referral(
                 %s, %s, %s, %s,
                 '{"site_code":"SYNTH-SITE","screening_priority":"routine","criteria_match_codes":["C02"]}'::jsonb,
                 'criteria-v1')""",
            (self.org_a, study_id, self.patient_a, 'REF-' + study_id[10:20]),
        )
        referral_id = c.fetchone()[0]

        # Trial member can receive the referral and create a separate study code.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.b,))
        c.execute(
            "SELECT public.jl_create_trial_participant_from_referral(%s, %s, %s, %s)",
            (self.org_a, referral_id, 'SYNTH-PART-' + study_id[:6], 'SYNTH-SITE'),
        )
        participant_id = c.fetchone()[0]
        c.execute(
            "SELECT status, consent_status FROM public.jl_trial_participants WHERE id=%s",
            (participant_id,),
        )
        self.assertEqual(c.fetchone(), ('screening', 'not_obtained'))

        # The trial participant schema has no hospital patient identifier, and the
        # private identity map is not addressable by an authenticated browser user.
        c.execute(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_schema='public' AND table_name='jl_trial_participants'
                 AND column_name IN ('patient_id','mrn','id_number','full_name')"""
        )
        self.assertEqual(c.fetchone()[0], 0)
        c.execute("SAVEPOINT private_identity_access_test")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                "SELECT hospital_patient_id FROM private.jl_trial_recruitment_identity_links WHERE referral_id=%s",
                (referral_id,),
            )
        c.execute("ROLLBACK TO SAVEPOINT private_identity_access_test")

        # Enrolment is blocked until consent has a version, outcome and controlled
        # source-document reference. The failed attempt is rolled back to a savepoint.
        c.execute("SAVEPOINT enrolment_without_consent_test")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                """SELECT public.jl_record_trial_participant_event(
                     %s,%s,'enrolled',now(),'recorded','Attempted enrolment','{}'::jsonb)""",
                (self.org_a, participant_id),
            )
        c.execute("ROLLBACK TO SAVEPOINT enrolment_without_consent_test")

        c.execute(
            """SELECT public.jl_record_trial_participant_event(
                 %s,%s,'consent_recorded',now(),'recorded','Consent evidence recorded',
                 '{"icf_version":"ICF-v1","consent_status":"obtained",
                   "consent_record_reference":"SYNTH-CONSENT-001"}'::jsonb)""",
            (self.org_a, participant_id),
        )
        c.execute(
            """SELECT public.jl_record_trial_participant_event(
                 %s,%s,'enrolled',now(),'recorded','Authorised enrolment recorded','{}'::jsonb)""",
            (self.org_a, participant_id),
        )
        c.execute(
            "SELECT status, consent_status, consent_record_reference FROM public.jl_trial_participants WHERE id=%s",
            (participant_id,),
        )
        self.assertEqual(c.fetchone(), ('enrolled', 'obtained', 'SYNTH-CONSENT-001'))

        # Server-side intelligence derives its evidence counts from canonical records,
        # not from client-supplied aggregate numbers.
        c.execute(
            """SELECT public.jl_record_trial_participant_event(
                 %s,%s,'visit_scheduled',now()-interval '2 days','scheduled',
                 'Synthetic overdue baseline visit','{"visit_name":"Baseline"}'::jsonb)""",
            (self.org_a, participant_id),
        )
        c.execute(
            """SELECT public.jl_record_trial_participant_event(
                 %s,%s,'protocol_deviation_recorded',now(),'recorded',
                 'Synthetic protocol deviation',
                 '{"deviation_category":"major","deviation_impact":"study_data"}'::jsonb)""",
            (self.org_a, participant_id),
        )
        c.execute(
            """SELECT public.jl_record_trial_participant_event(
                 %s,%s,'serious_adverse_event_recorded',now(),'open',
                 'Synthetic SAE follow-up record','{}'::jsonb)""",
            (self.org_a, participant_id),
        )
        c.execute("SELECT public.jl_build_trial_intelligence_checks(%s)", (self.org_a,))
        derived_checks = {item["check_id"]: item for item in c.fetchone()[0]}
        self.assertEqual(derived_checks["overdue_visit"]["evidence_count"], 1)
        self.assertEqual(derived_checks["protocol_deviation"]["evidence_count"], 1)
        self.assertEqual(derived_checks["adverse_event_followup"]["evidence_count"], 1)
        self.assertEqual(derived_checks["consent_record_incomplete"]["evidence_count"], 0)

        # The authorised Trial member can read the participant timeline and referral,
        # but cannot resolve the linked Hospital identity.
        c.execute(
            "SELECT count(*) FROM public.jl_trial_participant_events WHERE participant_id=%s",
            (participant_id,),
        )
        self.assertEqual(c.fetchone()[0], 6)
        c.execute(
            "SELECT status FROM public.jl_trial_recruitment_referrals WHERE id=%s",
            (referral_id,),
        )
        self.assertEqual(c.fetchone()[0], 'enrolled')

        # Organisation owners cannot revoke independent recruitment approval.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute("SAVEPOINT recruitment_revocation_denial")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute("SELECT public.jl_revoke_trial_recruitment(%s,'unauthorised test revocation')", (study_id,))
        c.execute("ROLLBACK TO SAVEPOINT recruitment_revocation_denial")

        # Platform Admin revocation is audited and immediately removes the study
        # from Hospital referral options.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.platform_admin,))
        c.execute("SELECT public.jl_revoke_trial_recruitment(%s,'synthetic test revocation')", (study_id,))
        # The platform administrator's revocation RPC is authoritative. Do not
        # bypass the study table's member-scoped RLS merely to inspect its row;
        # verify the effective state through the Hospital discovery function below.
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (self.a,))
        c.execute("SELECT * FROM public.jl_list_recruitable_trial_studies(%s)", (self.org_a,))
        self.assertEqual(c.fetchall(), [])
        c.execute("SAVEPOINT referral_after_revocation")
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            c.execute(
                """SELECT public.jl_create_trial_recruitment_referral(
                     %s,%s,%s,%s,'{"screening_priority":"routine"}'::jsonb,'criteria-v1')""",
                (self.org_a, study_id, self.patient_a, 'REF-REVOKED-' + study_id[:8]),
            )
        c.execute("ROLLBACK TO SAVEPOINT referral_after_revocation")

        c.execute("ROLLBACK TO SAVEPOINT governed_trial_recruitment_test")
        c.execute("RELEASE SAVEPOINT governed_trial_recruitment_test")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "conn", None):
            # Roll back all synthetic users, organisations, patients and events at once.
            cls.conn.rollback()
            cls.conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
