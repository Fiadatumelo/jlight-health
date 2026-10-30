"""Regression tests for isolated Clinical Trials JC scope."""
import unittest

from agent.jc_agent import JCContext, JCAgent, JCTool, JCForbidden
from engine.intelligence_engine import build_clinical_trials_intelligence_summary


class ClinicalTrialsJCTests(unittest.TestCase):
    def setUp(self):
        self.audit_events = []

    def audit(self, event):
        self.audit_events.append(dict(event))

    def test_trial_summary_accepts_only_allowlisted_aggregate_checks(self):
        result = build_clinical_trials_intelligence_summary(
            clinical_trials_checks=[
                {"check_id": "overdue_visit", "status": "review", "severity": "medium", "evidence_count": 3,
                 "rule_version": "ct-ops-2026.10.1",
                 "evidence_refs": [
                     {"source_table": "jl_trial_participant_events", "source_record_id": "evt-opaque-1",
                      "event_type": "visit_scheduled", "occurred_at": "2026-10-30T10:00:00Z"},
                     {"source_table": "jl_trial_participants", "source_record_id": "participant-id-must-not-leak",
                      "event_type": "consent_record_incomplete", "occurred_at": "2026-10-30T10:00:00Z"},
                 ]},
                {"check_id": "unapproved_free_text", "status": "fail", "severity": "critical", "evidence_count": 99},
                {"check_id": "participant_withdrawal", "status": "review", "severity": "low", "evidence_count": 1},
                {"check_id": "adverse_event_followup", "status": "pass", "severity": "info", "evidence_count": 0},
            ]
        )
        self.assertEqual(result["finding_count"], 3)
        self.assertEqual(result["status_counts"]["review"], 2)
        self.assertEqual(result["status_counts"]["pass"], 1)
        self.assertTrue(result["human_review_required"])
        self.assertNotIn("participant_id", str(result).lower())
        self.assertEqual(result["overall_status"], "review_required")
        self.assertEqual(result["rule_versions"], ["ct-ops-2026.10.1"])
        overdue = next(x for x in result["findings"] if x["rule_id"] == "overdue_visit")
        self.assertEqual(len(overdue["evidence"]["evidence_refs"]), 1)
        self.assertEqual(overdue["evidence"]["evidence_refs"][0]["source_record_id"], "evt-opaque-1")
        self.assertNotIn("participant-id-must-not-leak", str(result))

    def test_trial_scope_can_execute_trial_tool(self):
        context = JCContext("user-1", "org-1", frozenset({"intelligence:read"}), role="trial", clinical_trials_scope=True)
        agent = JCAgent(context=context, audit=self.audit)
        agent.register(JCTool(
            name="clinical_trials_summary",
            description="Trial-only summary",
            handler=lambda _ctx, args: build_clinical_trials_intelligence_summary(
                clinical_trials_checks=args["clinical_trials_checks"]
            ),
            required_permissions=frozenset({"intelligence:read"}),
            allowed_arguments=frozenset({"clinical_trials_checks"}),
            allowed_scopes=frozenset({"clinical_trials"}),
        ))
        result = agent.execute("clinical_trials_summary", {"clinical_trials_checks": []})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.audit_events[-1]["outcome"], "succeeded")

    def test_general_tool_cannot_execute_in_trial_scope(self):
        context = JCContext("user-1", "org-1", frozenset({"intelligence:read"}), clinical_trials_scope=True)
        agent = JCAgent(context=context, audit=self.audit)
        agent.register(JCTool(
            name="general_summary", description="General summary",
            handler=lambda _ctx, _args: {"ok": True},
            required_permissions=frozenset({"intelligence:read"}),
            allowed_scopes=frozenset({"general"}),
        ))
        with self.assertRaises(JCForbidden):
            agent.execute("general_summary", {})
        self.assertEqual(self.audit_events[-1]["reason"], "workspace_scope_mismatch")

    def test_trial_tool_cannot_execute_in_general_scope(self):
        context = JCContext("user-1", "org-1", frozenset({"intelligence:read"}))
        agent = JCAgent(context=context, audit=self.audit)
        agent.register(JCTool(
            name="trial_summary", description="Trial summary",
            handler=lambda _ctx, _args: {"ok": True},
            required_permissions=frozenset({"intelligence:read"}),
            allowed_scopes=frozenset({"clinical_trials"}),
        ))
        with self.assertRaises(JCForbidden):
            agent.execute("trial_summary", {})
        self.assertEqual(self.audit_events[-1]["reason"], "workspace_scope_mismatch")


if __name__ == "__main__":
    unittest.main()
