"""Authenticated Supabase RLS integration gates.

Run only against a disposable Supabase staging database. Every fixture is wrapped
in a transaction and rolled back. Never point this test at production.
"""
import os
import unittest
import uuid

try:
    import psycopg2
except ImportError:  # Keep the ordinary unit-test suite usable without integration deps.
    psycopg2 = None


STAGING_DSN = os.getenv("JLIGHT_STAGING_DATABASE_URL", "")
STAGING_REF = os.getenv("JLIGHT_STAGING_PROJECT_REF", "")
PRODUCTION_REF = os.getenv("JLIGHT_PRODUCTION_PROJECT_REF", "")


@unittest.skipUnless(STAGING_DSN and psycopg2, "staging database credentials are not configured")
class AuthenticatedSupabaseRLSGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STAGING_REF or not PRODUCTION_REF or STAGING_REF == PRODUCTION_REF:
            raise RuntimeError("Refusing RLS integration tests without distinct staging and production project refs")
        cls.conn = psycopg2.connect(STAGING_DSN)
        cls.conn.autocommit = False
        cls.a = str(uuid.uuid4())
        cls.b = str(uuid.uuid4())
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
        cls.participant = str(uuid.uuid4())
        cls._seed_transactional_fixtures()

    @classmethod
    def _seed_transactional_fixtures(cls):
        c = cls.conn.cursor()
        # Refuse to run against a database with the production project ref in its DSN.
        if PRODUCTION_REF in STAGING_DSN:
            raise RuntimeError("Staging DSN appears to reference the production project")
        for uid, email in ((cls.a, "rls-a@invalid.example"), (cls.b, "rls-b@invalid.example")):
            c.execute(
                """INSERT INTO auth.users
                   (id, aud, role, email, encrypted_password, email_confirmed_at,
                    raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
                   VALUES (%s, 'authenticated', 'authenticated', %s, '', now(),
                           '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now())""",
                (uid, email),
            )
        # Owner-membership seed triggers create the corresponding membership records.
        for org_id, name, email, uid, role in (
            (cls.org_a, "RLS synthetic hospital A", "rls-a@invalid.example", cls.a, "Hospital"),
            (cls.org_b, "RLS synthetic hospital B", "rls-b@invalid.example", cls.b, "Hospital"),
            (cls.trial_org, "RLS synthetic trial", "rls-a@invalid.example", cls.a, "Trial"),
        ):
            c.execute(
                """INSERT INTO public.jl_organisations
                   (id, name, role, owner_email, owner_user_id, type)
                   VALUES (%s, %s, %s, %s, %s, 'multi')""",
                (org_id, name, role, email, uid),
            )
        for org_id, uid in ((cls.org_a, cls.a), (cls.org_b, cls.b)):
            for domain in ("hospital", "laboratory", "bioinformatics"):
                c.execute(
                    """INSERT INTO public.jlight_membership_domain_permissions
                       (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
                       VALUES (%s, %s, %s, true, true, true, %s)""",
                    (org_id, uid, domain, uid),
                )
        c.execute(
            """INSERT INTO public.jlight_membership_domain_permissions
               (organization_id, auth_subject, domain, can_read, can_write, can_report, granted_by)
               VALUES (%s, %s, 'clinical_trials', true, true, true, %s)""",
            (cls.trial_org, cls.a, cls.a),
        )
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
        cls.conn.commit()

    def _as_user(self, uid):
        c = self.conn.cursor()
        c.execute("BEGIN")
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (uid,))
        return c

    def test_patient_matching_is_exact_and_organisation_scoped(self):
        c = self._as_user(self.a)
        c.execute("SELECT id FROM public.jl_patients WHERE mrn = 'PATION-001'")
        self.assertEqual([row[0] for row in c.fetchall()], [self.patient_a])
        c.execute("ROLLBACK")

    def test_cross_organisation_encounters_and_findings_are_hidden(self):
        c = self._as_user(self.a)
        c.execute("SELECT id FROM public.jl_encounters")
        self.assertEqual([row[0] for row in c.fetchall()], [self.encounter_a])
        c.execute("SELECT id FROM public.jl_intelligence_findings")
        self.assertEqual([row[0] for row in c.fetchall()], [self.finding_a])
        c.execute("ROLLBACK")

    def test_issue_resolution_history_is_tenant_scoped(self):
        c = self._as_user(self.a)
        c.execute("SELECT id, finding_id FROM public.jl_finding_review_events")
        self.assertEqual(c.fetchall(), [(self.event_a, self.finding_a)])
        c.execute("ROLLBACK")

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
        c.execute("ROLLBACK")

    def test_clinical_trials_records_are_not_visible_from_hospital_membership(self):
        c = self._as_user(self.b)
        c.execute("SELECT id FROM public.jl_trial_studies")
        self.assertEqual(c.fetchall(), [])
        c.execute("SELECT id FROM public.jl_trial_participants")
        self.assertEqual(c.fetchall(), [])
        c.execute("ROLLBACK")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "conn", None):
            # Remove all synthetic fixtures explicitly; never leave test patients in staging.
            try:
                cls.conn.rollback()
                c = cls.conn.cursor()
                c.execute(
                    "DELETE FROM public.jl_organisations WHERE id IN (%s, %s, %s)",
                    (cls.org_a, cls.org_b, cls.trial_org),
                )
                c.execute(
                    "DELETE FROM auth.users WHERE id IN (%s, %s)",
                    (cls.a, cls.b),
                )
                cls.conn.commit()
            except Exception:
                cls.conn.rollback()
                raise
            finally:
                cls.conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
