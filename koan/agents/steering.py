# Shared steering pipeline used by both the Claude PostToolUse hook
# (koan/agents/claude.py) and the codex/gemini MCP-handler path
# (koan/web/mcp_endpoint.py:_drain_and_append_steering).
#
# Three callables:
#   drain_for_primary -- SOLE drain entry per brief decision 5. Atomically
#       pops and clears the steering queue gated on agent.is_primary.
#   render_text       -- text formatter for the SDK PostToolUse hook's
#       additionalContext field. Attachments are dropped (text-only path).
#   render_blocks     -- block formatter for the codex/gemini MCP-handler
#       path. Produces envelope-open + per-message blocks + attachments +
#       envelope-close, matching today's _drain_and_append_steering output.

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import ContentBlock

    from ..state import AgentState, AppState, ChatMessage


def drain_for_primary(
    app_state: AppState,
    agent: AgentState | None,
) -> list[ChatMessage]:
    """Atomically drain the steering queue gated on primary-agent status.

    Returns [] when agent is None or agent.is_primary is False, preserving
    the queue for the next primary-agent drain. This is the SOLE drain entry
    per brief decision 5 -- both the Claude PostToolUse hook and the codex/
    gemini MCP-handler call this function. Centralising the drain prevents
    double-delivery bugs that two independent queue readers would introduce.

    Observability of the early-return path (agent is None or not is_primary)
    is intentionally NOT logged from this file. Instead, both callers emit a
    DEBUG log at their own call site using their own existing module loggers:
    - koan/agents/claude.py post_tool_use_hook (step 5b) uses koan.claude_sdk_agent
    - koan/web/mcp_endpoint.py _drain_and_append_steering (step 7b) uses koan.mcp
    This keeps koan/agents/steering.py free of its own logger per brief decision 4
    (no new logger names added in this changeset).
    """
    if agent is None or not agent.is_primary:
        return []
    from ..state import drain_steering_messages
    return drain_steering_messages(app_state)


def render_text(messages: list[ChatMessage]) -> str:
    """Format drained steering messages as a single string for SDK additionalContext.

    Produces the steering envelope open text, one line per message (timestamp +
    optional artifact prefix + content), and the envelope close tag. Attachments
    are not rendered -- additionalContext is text-only; attachment fidelity is
    intentionally dropped on this path per brief decision 4.

    Returns "" when messages is empty so callers can short-circuit cheaply.
    """
    if not messages:
        return ""
    # Mirror the envelope structure from koan/phases/format_step.py:
    # steering_envelope_open / steering_message_block / steering_envelope_close.
    # Inlined here to produce a flat string rather than ContentBlock objects.
    header = (
        "\n\n<steering>\n"
        "The user sent the following message(s) while you were working. "
        "Take these into account going forward, but do not abandon the "
        "current workflow step. Integrate the feedback into your approach.\n"
    )
    lines = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
        ts_str = ts.strftime("%H:%M:%S UTC")
        body = msg.content
        if msg.artifact_path:
            body = f"[artifact: {msg.artifact_path}] {body}"
        lines.append(f"[{ts_str}] {body}")
    return header + "\n".join(lines) + "\n</steering>"


def render_blocks(
    messages: list[ChatMessage],
    app_state: AppState,
    agent: AgentState | None,
) -> tuple[list[ContentBlock], list[dict]]:
    """Format drained steering messages as ContentBlock list with attachment support.

    Returns (steering_blocks, manifest) where steering_blocks contains
    envelope-open + per-message-block + per-message-attachment-blocks +
    envelope-close, matching today's _drain_and_append_steering output shape.
    Returns ([], []) when messages is empty.

    agent is used only to determine runner_type for upload_ids_to_blocks, which
    decides whether to produce File/Image blocks or a text-notice fallback.
    """
    if not messages:
        return [], []

    from ..phases.format_step import (
        steering_envelope_close,
        steering_envelope_open,
        steering_message_block,
    )
    from ..web.uploads import upload_ids_to_blocks

    runner_type = agent.runner_type if agent is not None else ""
    run_dir = app_state.run.run_dir or ""

    blocks: list[ContentBlock] = []
    manifest: list[dict] = []

    blocks.append(steering_envelope_open())
    for msg in messages:
        blocks.append(steering_message_block(msg))
        if msg.attachments:
            bs, ms = upload_ids_to_blocks(
                app_state.uploads,
                run_dir,
                msg.attachments,
                runner_type,
            )
            blocks.extend(bs)
            manifest.extend(ms)
    blocks.append(steering_envelope_close())
    return blocks, manifest
