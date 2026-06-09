# Step prompt assembly -- formats StepGuidance into strings returned to the LLM.
#
# format_step()          -- normal step guidance with WHEN DONE footer;
#                           the footer tells the agent to end its turn once the
#                           step's work is done -- end-of-turn advances to the
#                           next step automatically via the loop resolver.
# terminal_invoke()      -- invoke_after footer for the last step of a phase;
#                           auto-advance (koan_set_phase) or hand back to the
#                           user depending on whether next_phase is bound.
# format_user_messages()  -- formats buffered user messages for delivery to the
#                            LLM when the loop resumes after a hand-back.
# format_steering_messages() -- formats steering queue for inline delivery.

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mcp.types import ContentBlock, TextContent

if TYPE_CHECKING:
    from . import StepGuidance


DEFAULT_INVOKE = (
    "WHEN DONE: end your turn once this step's work is complete -- a turn that"
    " ends with no further tool call advances you to the next step automatically."
    " Do not end your turn until the step's work is done."
)


def format_step(g: StepGuidance) -> str:
    """Format a StepGuidance into a string delivered to the LLM as the turn prompt.

    Appends g.invoke_after when provided, or DEFAULT_INVOKE (the end-of-turn
    advances model) when not. The step title and instructions are preserved verbatim.
    """
    header = f"{g.title}\n{'=' * len(g.title)}\n\n"
    body = "\n".join(g.instructions)
    invoke = g.invoke_after if g.invoke_after is not None else DEFAULT_INVOKE
    return f"{header}{body}\n\n{invoke}"


def format_user_messages(messages: list[Any]) -> list[ContentBlock]:
    """Wrap user chat messages in a user-voice envelope for the LLM.

    Returns one TextContent block per message so M3 can interleave File
    blocks adjacent to each message without re-splitting a joined string.
    The envelope is content-agnostic: whether the payload is a review
    response, a direct reply, or an open-ended message, the framing only
    asserts "the user said this". Behavior-specific instructions live in
    the message body. Do NOT add review-aware branching here: handoff
    minimalism requires this layer to stay ignorant of what kind of user
    message it is wrapping.
    """
    blocks: list[ContentBlock] = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
        ts_str = ts.strftime("%H:%M:%S UTC")
        blocks.append(TextContent(
            type="text",
            text=f"---\nUSER MESSAGE (at {ts_str}):\n{msg.content}\n---",
        ))
    return blocks


def steering_envelope_open() -> TextContent:
    """Opening fence for a steering block.

    Returned as a separate block so _drain_and_append_steering can interleave
    per-message File/Image attachment blocks between the open and close fences.
    """
    return TextContent(type="text", text=(
        "\n\n<steering>\n"
        "The user sent the following message(s) while you were working. "
        "Take these into account going forward, but do not abandon the "
        "current workflow step. Integrate the feedback into your approach.\n"
    ))


def steering_message_block(msg: Any) -> TextContent:
    """Format a single steering message as a TextContent block.

    When msg.artifact_path is set, prefix the body with [artifact: {path}]
    so the orchestrator can route the comment to the right artifact context.
    """
    ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
    ts_str = ts.strftime("%H:%M:%S UTC")
    body = msg.content
    artifact_path = getattr(msg, "artifact_path", None)
    if artifact_path:
        body = f"[artifact: {artifact_path}] {body}"
    return TextContent(type="text", text=f"[{ts_str}] {body}")


def steering_envelope_close() -> TextContent:
    """Closing fence for a steering block."""
    return TextContent(type="text", text="</steering>")


def format_steering_messages(messages: list[Any]) -> list[ContentBlock]:
    """Format steering queue messages into a clearly demarcated XML block.

    Returns a single-element list carrying the full steering envelope.
    Preserved for callers that need the plain-string representation without
    per-message interleaving. _drain_and_append_steering uses the three
    steering_envelope_* helpers directly for per-message attachment support.
    """
    parts = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
        ts_str = ts.strftime("%H:%M:%S UTC")
        body = msg.content
        artifact_path = getattr(msg, "artifact_path", None)
        if artifact_path:
            body = f"[artifact: {artifact_path}] {body}"
        parts.append(f"[{ts_str}] {body}")
    body = "\n\n".join(parts)
    envelope = (
        "\n\n<steering>\n"
        "The user sent the following message(s) while you were working.\n"
        "Take these into account going forward, but do not abandon the\n"
        "current workflow step. Integrate the feedback into your approach.\n"
        "\n"
        f"{body}\n"
        "</steering>"
    )
    return [TextContent(type="text", text=envelope)]


def terminal_invoke(next_phase: str | None, suggested_phases: list[str]) -> str:
    """Render the invoke_after footer for the last step of a phase.

    When next_phase is bound, the LLM is told to call koan_set_phase directly
    (auto-advance). When next_phase is None, the LLM is told to end its turn
    with a plain-text summary -- a turn with no tool call is the hand-back: the
    loop parks and waits for the user's next message.

    Auto-advance is guidance: the LLM may hand back instead if exceptional
    circumstances warrant user direction.

    Pure function -- no app_state or workflow lookup. Inputs are typed and
    come from PhaseContext (populated at step-1 handshake).
    """
    if next_phase is not None:
        return (
            "WHEN DONE:\n"
            "1. Summarize what was accomplished in this phase as your final message.\n"
            f'2. Default: call `koan_set_phase("{next_phase}")` to advance to the next phase.\n'
            "3. If exceptional circumstances warrant user direction, end your turn\n"
            "   with that summary and your recommended next steps as a plain-text\n"
            "   message (do NOT call a tool) -- ending your turn hands control back\n"
            "   to the user, who will reply with how to proceed.\n"
            "\n"
            "The directive above is the terminal action for this phase."
        )

    # next_phase is None -- hand back to the user with the next-phase options
    # listed in the summary. Render the options hint from the phase's transition
    # list so the LLM has concrete choices without looking up the workflow.
    suggestions_hint = ", ".join(suggested_phases) if suggested_phases else ""
    suggestions_clause = (
        f" (e.g. {suggestions_hint})" if suggestions_hint else ""
    )
    return (
        "WHEN DONE:\n"
        "1. Summarize what was accomplished in this phase as your final message,\n"
        f"   and list the reasonable next-phase options{suggestions_clause}, plus\n"
        '   the option to end the workflow ("done").\n'
        "2. End your turn with that summary as a plain-text message (do NOT call a\n"
        "   tool). A turn with no tool call is the hand-back: the loop parks and\n"
        "   waits for the user's reply.\n"
        "3. Once the user confirms a direction, call `koan_set_phase(<phase>)` (or\n"
        '   `koan_set_phase("done")` to end the workflow).\n'
        "\n"
        "Ending your turn is the terminal action for this phase."
    )
