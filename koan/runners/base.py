# Runner protocol, StreamEvent, and RunnerDiagnostic.
# Defines the contract that all CLI runner adapters must satisfy.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..types import AgentInstallation, ModelInfo, ThinkingMode


@dataclass(kw_only=True)
class StreamEvent:
    type: Literal[
        "token_delta", "turn_complete", "tool_call", "thinking", "assistant_text",
        "tool_start", "tool_input_delta", "tool_stop", "tool_result",
    ]
    content: str | None = None
    is_thinking: bool = False
    tool_name: str | None = None
    tool_args: dict | None = None
    summary: str | None = None
    tool_use_id: str | None = None
    block_index: int | None = None
    # Populated for tool_result events: tool-family-specific metrics parsed
    # from the model's tool_result block content. None when the runner could
    # not interpret the result; the consumer treats this as "no metrics" and
    # leaves projection state unchanged for that call_id.
    metrics: dict | None = None


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
        system_prompt: str = "",
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
    "koan_set_phase",
    "koan_yield",
    "koan_request_scouts",
    "koan_ask_question",
    "koan_request_executor",
    "koan_select_story",
    "koan_complete_story",
    "koan_retry_story",
    "koan_skip_story",
    "koan_memorize",
    "koan_forget",
    "koan_memory_status",
    "koan_search",
})
