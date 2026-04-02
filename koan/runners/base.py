# Runner protocol, StreamEvent, and RunnerDiagnostic.
# Defines the contract that all CLI runner adapters must satisfy.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..types import AgentInstallation, ModelInfo, ThinkingMode


@dataclass(kw_only=True)
class StreamEvent:
    type: Literal["token_delta", "turn_complete", "tool_call", "thinking", "assistant_text"]
    content: str | None = None
    is_thinking: bool = False
    tool_name: str | None = None
    tool_args: dict | None = None
    summary: str | None = None


@dataclass(kw_only=True)
class RunnerDiagnostic:
    code: str
    runner: str
    stage: str
    message: str
    details: dict | None = None


class RunnerError(RuntimeError):
    def __init__(self, diagnostic: RunnerDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class Runner(Protocol):
    name: str
    supported_thinking_modes: frozenset[ThinkingMode]

    def build_command(
        self,
        boot_prompt: str,
        mcp_url: str,
        installation: AgentInstallation,
        model: str,
        thinking: ThinkingMode,
    ) -> list[str]: ...

    def list_models(self, binary: str) -> list[ModelInfo]: ...

    def parse_stream_event(self, line: str) -> list[StreamEvent]: ...


# Tool names registered in koan's MCP server. Runners filter stdout tool events
# whose names appear here to prevent duplicate tool_called/tool_completed events
# (the MCP endpoint is the authoritative source for koan MCP calls).
#
# MAINTENANCE: this set must stay in sync with the @mcp.tool() registrations in
# koan/web/mcp_endpoint.py. It lives in base.py (not mcp_endpoint.py) to avoid a
# circular import (mcp_endpoint imports from subagent which imports from runners).
# When adding a new koan MCP tool to mcp_endpoint.py, update this set too.
KOAN_MCP_TOOLS: frozenset[str] = frozenset({
    "koan_complete_step",
    "koan_set_confidence",
    "koan_request_scouts",
    "koan_ask_question",
    "koan_review_artifact",
    "koan_propose_workflow",
    "koan_set_next_phase",
})
