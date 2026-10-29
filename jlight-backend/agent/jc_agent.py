"""JC — JLIGHT's in-process, policy-enforced tool orchestration core.

This module deliberately contains no HTTP route and no model-provider dependency.
The existing authenticated JLIGHT request handler should construct a request-scoped
JCAgent and register only existing, authorised JLIGHT functions as tools.

Do not register arbitrary shell, SQL, filesystem, network, or unrestricted Python tools.
Do not pass raw patient identifiers, sequences, or other sensitive payloads to a model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
import re


class JCError(Exception):
    """Base exception for safe JC failures."""


class JCForbidden(JCError):
    """Raised when the caller lacks permission to run a tool."""


class JCApprovalRequired(JCError):
    """Raised when a tool needs explicit approval."""


class JCInvalidRequest(JCError):
    """Raised when a request or tool result is malformed."""


@dataclass(frozen=True)
class JCContext:
    """Verified request identity and tenant boundary, supplied by JLIGHT auth."""
    user_id: str
    organisation_id: str
    permissions: frozenset[str]
    role: str = ""
    clinical_trials_scope: bool = False

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.organisation_id.strip():
            raise JCInvalidRequest("Verified user and organisation context are required.")
        if self.clinical_trials_scope:
            raise JCForbidden("JC core tools are not enabled for Clinical Trials context.")


@dataclass(frozen=True)
class JCTool:
    """An explicitly allowlisted JLIGHT function; never arbitrary code."""
    name: str
    description: str
    handler: Callable[[JCContext, Mapping[str, Any]], Mapping[str, Any]]
    required_permissions: frozenset[str] = frozenset()
    requires_approval: bool = False
    allowed_arguments: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", self.name):
            raise JCInvalidRequest("Tool names must be stable lowercase identifiers.")
        if not callable(self.handler):
            raise JCInvalidRequest("Tool handler must be callable.")


@dataclass
class JCAgent:
    """Request-scoped JC controller that selects and verifies allowlisted tools.

    This core does not guess tools from arbitrary user text. The authenticated
    JLIGHT layer must map a validated intent to an explicit tool name and arguments.
    """
    context: JCContext
    audit: Callable[[Mapping[str, Any]], None] | None = None
    tools: dict[str, JCTool] = field(default_factory=dict)

    def register(self, tool: JCTool) -> None:
        if tool.name in self.tools:
            raise JCInvalidRequest(f"Duplicate JC tool registration: {tool.name}")
        self.tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, str]]:
        """Return only tools this caller is permitted to discover."""
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self.tools.values()
            if tool.required_permissions.issubset(self.context.permissions)
        ]

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Execute one allowlisted tool and return a verified, bounded result."""
        if not isinstance(tool_name, str) or tool_name not in self.tools:
            raise JCInvalidRequest("Unknown JC tool.")
        tool = self.tools[tool_name]
        args = dict(arguments or {})

        if not tool.required_permissions.issubset(self.context.permissions):
            self._audit(tool_name, "denied", "missing_permission")
            raise JCForbidden("You do not have permission to perform this action.")

        unexpected = set(args) - set(tool.allowed_arguments)
        if unexpected:
            raise JCInvalidRequest("Tool arguments contain unsupported fields.")
        if tool.requires_approval and not approved:
            self._audit(tool_name, "approval_required", "human_approval")
            raise JCApprovalRequired("Explicit approval is required before this action.")

        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = tool.handler(self.context, args)
            if not isinstance(result, Mapping):
                raise JCInvalidRequest("Tool returned an invalid result.")
            # Return JSON-safe, bounded metadata only. Tool handlers should return
            # summaries/references, not raw patient records or sequence payloads.
            safe_result = self._validate_result(result)
            self._audit(tool_name, "succeeded", "verified_return")
            return {
                "agent": "JC",
                "tool": tool_name,
                "status": "succeeded",
                "started_at": started_at,
                "result": safe_result,
            }
        except JCError:
            self._audit(tool_name, "failed", "jc_validation_error")
            raise
        except Exception as exc:
            # Do not return exception text: it may contain secrets or patient data.
            self._audit(tool_name, "failed", type(exc).__name__)
            return {
                "agent": "JC",
                "tool": tool_name,
                "status": "failed",
                "started_at": started_at,
                "error": "The requested operation failed. Check the JLIGHT audit record.",
            }

    def _audit(self, tool: str, outcome: str, reason: str) -> None:
        if self.audit is None:
            return
        # Intentionally omit arguments, results, user content, and patient data.
        event = {
            "agent": "JC",
            "tool": tool,
            "outcome": outcome,
            "reason": reason,
            "user_id": self.context.user_id,
            "organisation_id": self.context.organisation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.audit(event)
        except Exception:
            # Audit persistence should be wired to JLIGHT's mandatory audit path.
            # Never misreport a tool result as successful if that path is unavailable.
            raise JCError("JC audit logging failed; operation status cannot be confirmed.")

    @staticmethod
    def _validate_result(result: Mapping[str, Any]) -> dict[str, Any]:
        import json

        safe = dict(result)
        try:
            encoded = json.dumps(safe, allow_nan=False)
        except (TypeError, ValueError):
            raise JCInvalidRequest("Tool returned a non-JSON result.") from None
        if len(encoded.encode("utf-8")) > 16_384:
            raise JCInvalidRequest("Tool result exceeds the allowed response size.")
        return safe
