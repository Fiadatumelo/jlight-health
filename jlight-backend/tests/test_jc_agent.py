"""Regression tests for the JC in-process agent core.

Run from jlight-backend:
    python -m pytest tests/test_jc_agent.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.jc_agent import (
    JCApprovalRequired,
    JCContext,
    JCError,
    JCForbidden,
    JCInvalidRequest,
    JCAgent,
    JCTool,
)


def make_context(*permissions):
    return JCContext(
        user_id="user-test-1",
        organisation_id="org-test-1",
        permissions=frozenset(permissions),
    )


def make_audit(events):
    def audit(event):
        events.append(dict(event))
    return audit


def test_execute_allowlisted_tool_and_audit_without_arguments():
    events = []
    called = []
    agent = JCAgent(make_context("system:read"), audit=make_audit(events))
    agent.register(JCTool(
        name="system_status",
        description="Read a safe system status summary.",
        handler=lambda ctx, args: called.append((ctx.organisation_id, dict(args))) or {"status": "ok"},
        required_permissions=frozenset({"system:read"}),
        allowed_arguments=frozenset(),
    ))

    result = agent.execute("system_status")

    assert result["agent"] == "JC"
    assert result["status"] == "succeeded"
    assert result["result"] == {"status": "ok"}
    assert called == [("org-test-1", {})]
    assert events[-1]["outcome"] == "succeeded"
    assert "arguments" not in events[-1]
    assert "result" not in events[-1]


def test_unknown_tool_is_rejected():
    agent = JCAgent(make_context("system:read"), audit=make_audit([]))
    with pytest.raises(JCInvalidRequest, match="Unknown JC tool"):
        agent.execute("run_shell_command")


def test_missing_permission_blocks_execution():
    events = []
    called = []
    agent = JCAgent(make_context("system:read"), audit=make_audit(events))
    agent.register(JCTool(
        name="resolve_issue",
        description="Resolve an issue.",
        handler=lambda ctx, args: called.append(True) or {"resolved": True},
        required_permissions=frozenset({"issue:resolve"}),
    ))

    with pytest.raises(JCForbidden):
        agent.execute("resolve_issue")

    assert called == []
    assert events[-1]["outcome"] == "denied"


def test_sensitive_action_requires_explicit_approval():
    events = []
    called = []
    agent = JCAgent(make_context("report:write"), audit=make_audit(events))
    agent.register(JCTool(
        name="generate_report",
        description="Generate an approved report.",
        handler=lambda ctx, args: called.append(True) or {"report_id": "report-test"},
        required_permissions=frozenset({"report:write"}),
        requires_approval=True,
    ))

    with pytest.raises(JCApprovalRequired):
        agent.execute("generate_report")

    assert called == []
    result = agent.execute("generate_report", approved=True)
    assert result["status"] == "succeeded"
    assert called == [True]


def test_general_tools_are_blocked_in_clinical_trials_scope():
    events = []
    context = JCContext(
        user_id="user-test-1",
        organisation_id="org-test-1",
        permissions=frozenset({"system:read"}),
        clinical_trials_scope=True,
    )
    agent = JCAgent(context, audit=make_audit(events))
    agent.register(JCTool(
        name="system_status",
        description="General workspace status.",
        handler=lambda ctx, args: {"status": "ok"},
        required_permissions=frozenset({"system:read"}),
    ))
    with pytest.raises(JCForbidden, match="current workspace"):
        agent.execute("system_status")
    assert events[-1]["reason"] == "workspace_scope_mismatch"


def test_unsupported_arguments_are_rejected_before_execution():
    called = []
    agent = JCAgent(make_context("system:read"), audit=make_audit([]))
    agent.register(JCTool(
        name="system_status",
        description="Read system status.",
        handler=lambda ctx, args: called.append(True) or {"status": "ok"},
        allowed_arguments=frozenset({"component"}),
    ))

    with pytest.raises(JCInvalidRequest, match="unsupported fields"):
        agent.execute("system_status", {"sql": "SELECT * FROM patients"})
    assert called == []


def test_handler_failure_does_not_leak_exception_details():
    events = []
    agent = JCAgent(make_context("system:read"), audit=make_audit(events))
    agent.register(JCTool(
        name="system_status",
        description="Read system status.",
        handler=lambda ctx, args: (_ for _ in ()).throw(RuntimeError("secret patient payload")),
    ))

    result = agent.execute("system_status")

    assert result["status"] == "failed"
    assert "secret patient payload" not in str(result)
    assert events[-1]["outcome"] == "failed"


def test_execution_fails_closed_without_audit_sink():
    agent = JCAgent(make_context("system:read"))
    agent.register(JCTool(
        name="system_status",
        description="Read system status.",
        handler=lambda ctx, args: {"status": "ok"},
    ))

    with pytest.raises(JCError, match="audit sink"):
        agent.execute("system_status")


def test_audit_records_are_tenant_scoped_and_do_not_include_payloads():
    events = []
    agent = JCAgent(make_context("system:read"), audit=make_audit(events))
    agent.register(JCTool(
        name="system_status",
        description="Read system status.",
        handler=lambda ctx, args: {"status": "ok"},
        allowed_arguments=frozenset({"component"}),
    ))
    agent.execute("system_status", {"component": "bioinformatics"})

    event = events[-1]
    assert event["user_id"] == "user-test-1"
    assert event["organisation_id"] == "org-test-1"
    assert "component" not in event
