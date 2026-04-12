# Step prompt assembly -- formats StepGuidance into strings returned to the LLM.
#
# format_step()          -- normal step guidance with WHEN DONE footer
# format_phase_complete() -- non-blocking response when a phase ends; instructs
#                            the orchestrator to summarize and call koan_yield
# format_user_messages()  -- formats buffered user messages for inclusion in
#                            koan_yield's tool result
# format_steering_messages() -- formats steering queue for inline delivery

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import StepGuidance


DEFAULT_INVOKE = (
    "WHEN DONE: Call koan_complete_step to advance to the next step.\n"
    "Do NOT call this tool until the work described in this step is finished."
)


def format_step(g: StepGuidance) -> str:
    header = f"{g.title}\n{'=' * len(g.title)}\n\n"
    body = "\n".join(g.instructions)
    invoke = g.invoke_after if g.invoke_after is not None else DEFAULT_INVOKE
    return f"{header}{body}\n\n{invoke}"


def format_user_messages(messages: list[Any]) -> str:
    """Wrap user chat messages in a user-voice envelope for the LLM.

    The envelope is content-agnostic: whether the payload is a review
    response, a direct reply, or an open-ended message, the framing only
    asserts "the user said this". Behavior-specific instructions live in
    the message body (e.g. formatReviewMessage in the frontend names the
    review-revise-reyield loop). Do NOT add review-aware branching here:
    handoff minimalism requires this layer to stay ignorant of what kind
    of user message it is wrapping.
    """
    parts = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
        ts_str = ts.strftime("%H:%M:%S UTC")
        parts.append(f"---\nUSER MESSAGE (at {ts_str}):\n{msg.content}\n---")
    return "\n\n".join(parts)


def format_steering_messages(messages: list[Any]) -> str:
    """Format steering queue messages into a clearly demarcated XML block.

    Appended to tool responses so the LLM sees user feedback that arrived
    while it was working. The framing instructs the LLM to integrate the
    feedback without derailing from the current workflow.
    """
    parts = []
    for msg in messages:
        ts = datetime.fromtimestamp(msg.timestamp_ms / 1000, tz=timezone.utc)
        ts_str = ts.strftime("%H:%M:%S UTC")
        parts.append(f"[{ts_str}] {msg.content}")
    body = "\n\n".join(parts)
    return (
        "\n\n<steering>\n"
        "The user sent the following message(s) while you were working.\n"
        "Take these into account going forward, but do not abandon the\n"
        "current workflow step. Integrate the feedback into your approach.\n"
        "\n"
        f"{body}\n"
        "</steering>"
    )


def format_phase_complete(
    phase: str,
    suggested_phases: list[str],
    descriptions: dict[str, str] | None = None,
) -> str:
    """Non-blocking response when a phase completes.

    Tells the orchestrator to summarize its work and call koan_yield with
    structured suggestions. Does not block --koan_yield handles blocking.

    Args:
        phase: The phase that just completed (e.g. "intake").
        suggested_phases: Ordered list of suggested next phase IDs from the workflow.
        descriptions: Phase descriptions from the workflow definition.
    """
    title = f"Phase Complete: {phase}"
    lines = [title, "=" * len(title), ""]

    lines.append("Summarize what was accomplished in this phase.")
    lines.append("")

    descs = descriptions or {}

    if suggested_phases:
        lines.append("Then call `koan_yield` with suggestions for the user.")
        lines.append("Available phases:")
        lines.append("")
        for p in suggested_phases:
            desc = descs.get(p, "")
            if desc:
                lines.append(f"- **{p}** --{desc}")
            else:
                lines.append(f"- **{p}**")
        lines.append("")
        lines.append("For each suggestion, provide:")
        lines.append("- id: the phase name (e.g. \"plan-spec\")")
        lines.append("- label: a short action label (e.g. \"Write implementation plan\")")
        lines.append("- command: a task-specific sentence capturing what would be done")
        lines.append("  (e.g. \"write dashboard redesign implementation plan\")")
        lines.append("")
        lines.append("Always include a suggestion with id \"done\", label \"End workflow\",")
        lines.append("and a brief farewell command summarising what was accomplished.")
    else:
        lines.append("This workflow has no further phases. Call `koan_yield` with a single")
        lines.append("suggestion: id \"done\", label \"End workflow\", command describing")
        lines.append("what was accomplished. Let the user know the workflow ends here.")

    lines.append("")
    lines.append("WHEN DONE: Call koan_yield with your suggestions.")
    lines.append("Do NOT call koan_set_phase yet --wait for the user's response.")

    return "\n".join(lines)
