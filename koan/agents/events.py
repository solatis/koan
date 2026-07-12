# StreamEvent vocabulary + the koan MCP tool-name set.
#
# Relocated here from koan/runners/base.py (M9 rip-out): these two symbols
# outlive the CLI-runner layer (StreamEvent is the agent<->driver event
# vocabulary the PydanticAI path emits; KOAN_MCP_TOOLS is how the projection
# fold classifies koan tool calls), so they move to a surviving module before
# koan/runners/ is deleted. The Runner protocol stays in runners/base.py and is
# deleted with the CLI runners.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    # Lazy import -- pydantic_ai is heavy and RequestUsage is only needed for
    # the type annotation on StreamEvent.usage.
    from pydantic_ai.usage import RequestUsage


@dataclass(kw_only=True)
class StreamEvent:
    type: Literal[
        "token_delta", "turn_complete", "thinking", "assistant_text",
        "tool_start", "tool_input_delta", "tool_stop", "tool_result",
        "tool_failed",
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
    # Populated for tool_result events: attachment metadata extracted from
    # EmbeddedResource/ImageContent blocks in the tool_result content. None
    # when no attachment blocks are present or the runner cannot extract them.
    attachments: list[dict] | None = None
    # Populated on the request-final event (turn_complete) by PydanticAIAgent
    # with the per-request RequestUsage from pydantic-ai. None for all other
    # event types.
    usage: RequestUsage | None = None


# Tool names registered in koan's MCP server / in-process koan toolset. The
# projection fold uses this set to select ToolKoanEntry for any koan tool call.
KOAN_MCP_TOOLS: frozenset[str] = frozenset({
    # The step-advancement tool was removed in M6; end-of-turn is the signal.
    "koan_suggest_next",
    "koan_set_phase",
    "koan_request_scouts",
    # koan_request_executor re-added in M4 of the living-documents initiative:
    # the tool is phase-gated to execute and allows free-form executor launches
    # in addition to (or instead of) a named plan.
    "koan_request_executor",
    "koan_ask_question",
    # Story tools (koan_select/complete/retry/skip_story) removed in M1:
    # the legacy "execution" phase that gated them is deleted.
    "koan_memorize",
    "koan_forget",
    "koan_memory_status",
    "koan_search",
    "koan_reflect",
    "koan_artifact_write",
    # koan_artifact_edit added in M3: the orchestrator appends sidecar
    # dispositions with it, and the projection fold must classify it as a
    # koan tool call. Previously absent because the artifact edit tool
    # was not load-bearing for the fold.
    "koan_artifact_edit",
    # koan_memory_propose removed in M7: curation writes memory directly via
    # koan_memorize/koan_forget; the propose/approve gate is retired.
    "koan_artifact_list",
    "koan_artifact_read",
})
