# Handover-artifact injection for the koan orchestrator.
#
# Analog of koan/tools/context_files.py for phase handover artifacts.
# Implements the pre-seed injection mechanism: at phase entry, immutable
# required artifacts (brief.md, core-flows.md, tech-plan.md) are wrapped
# in a <handoff_artifact> envelope and appended to the agent's message
# history as distinct user messages before the step prompt.  Living-document
# families (plan, milestones) are never injected -- they appear in the
# read-on-demand filename listing and are read via koan_artifact_read.
#
# Key invariants:
#   - Injection is append-only (cache-prefix stability).
#   - Each artifact is injected at most once per agent lifetime (dedup via
#     AgentState.injected_artifacts).
#   - Absent declared artifacts are silently skipped (producer phase may
#     have been yield-skipped); genuine I/O faults produce a visible error
#     placeholder so gaps are never hidden.
#   - This module has no side effects at import time.

from __future__ import annotations

import os
from pathlib import Path

from pydantic_ai.messages import CachePoint, ModelRequest, UserPromptPart

from .artifact_registry import LIVING_DOC_FAMILIES, parse_artifact_filename
from ..agents.dialects import cache_ttl_for
from ..types import cache_tier_for_role

from ..phases import PhaseContext
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..state import AgentState, AppState


def __getattr__(name: str):
    # PEP 562: resolve the state types lazily. This module sits inside
    # state.py's own import chain (state -> projections -> workflows -> phases
    # -> executor -> here), so a top-level state import is circular. --debug
    # runtime type enforcement (beartype) resolves annotation names via
    # getattr on this module at call time, when koan.state is fully loaded.
    if name in ("AgentState", "AppState"):
        from .. import state
        return getattr(state, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
def format_handoff_message(name: str, content: str, error: bool = False) -> str:
    """Wrap artifact content in a <handoff_artifact> envelope.

    The envelope is deliberately distinct from the context-file
    <project_instructions> envelope and from steering envelopes, so the
    three message kinds are never conflated at read time.  When error is
    True, an error="true" attribute signals that the content is a
    placeholder, not real artifact content.

    Args:
        name: Artifact filename (e.g. "brief.md").
        content: Full text content of the artifact.
        error: When True, adds error="true" to the opening tag.
    """
    tag = f'<handoff_artifact name="{name}"'
    if error:
        tag += ' error="true"'
    tag += ">"
    return f"{tag}\n{content}\n</handoff_artifact>"


def select_immutable_handovers(required: tuple[str, ...], injected: set[str]) -> list[str]:
    """Return the not-yet-injected immutable filenames from required, in order.

    Pure selection step: immutable-only (family not in LIVING_DOC_FAMILIES),
    dedup-aware (skips names already in injected), order-preserving.  Names
    that do not parse as valid artifact filenames are silently skipped.

    Args:
        required: Ordered tuple of artifact filenames from PhaseBinding.required_artifacts.
        injected: Set of filenames already injected for this agent.
    """
    result = []
    for name in required:
        if name in injected:
            continue
        coord = parse_artifact_filename(name)
        if coord is None:
            continue
        # Only immutable families are ever injected; living documents (plan,
        # milestones) stay in the listing so they are always read fresh.
        if coord.family in LIVING_DOC_FAMILIES:
            continue
        result.append(name)
    return result


def build_handover_listing(run_dir: str, exclude: set[str]) -> str:
    """Build a read-on-demand filename listing of artifacts not in exclude.

    Lists only filenames that parse as valid artifact names and are not in
    exclude.  Because only immutable artifacts are ever injected (and
    therefore in exclude), this listing always includes every living document.
    Returns "" when run_dir is empty, unreadable, or nothing remains after
    exclusion.

    Args:
        run_dir: Path to the run directory to list.
        exclude: Filenames to omit (already-injected plus pending).
    """
    if not run_dir:
        return ""
    try:
        names = os.listdir(run_dir)
    except OSError:
        return ""
    available = sorted(
        n for n in names
        if parse_artifact_filename(n) is not None and n not in exclude
    )
    if not available:
        return ""
    lines = ["## Artifacts available to read on demand", ""]
    lines.extend(f"- `{n}`" for n in available)
    lines.append("")
    lines.append("Read any of the above with `koan_artifact_read` for optional context.")
    return "\n".join(lines)


def living_artifacts(names: list[str]) -> list[str]:
    """Return the living-document subset (plans, milestones) of names, in order.

    Living documents are those whose parsed family IS in LIVING_DOC_FAMILIES.
    Names that do not parse as valid artifact filenames are silently skipped.
    These are the artifacts the executor reads on demand -- listed, not injected.

    Args:
        names: Ordered list of artifact filenames to filter.
    """
    result = []
    for name in names:
        coord = parse_artifact_filename(name)
        if coord is None:
            continue
        if coord.family in LIVING_DOC_FAMILIES:
            result.append(name)
    return result


def subagent_candidates(ctx: PhaseContext) -> tuple[str, ...]:
    """Return the candidate artifact filenames for a subagent.

    The immutable filter (select_immutable_handovers) is applied later;
    this returns the full candidate set before filtering.

    For an executor: the full executor_artifacts list (living ones fall into
    the listing; immutable ones are injected).
    For a reviewer: brief.md plus the charter's upstream artifacts, mirroring
    the read directives in reviewer.py step_guidance(); the reviewer_target is
    deliberately excluded because it is always read explicitly via
    koan_artifact_read -- it is the focus of the review, not a standing handover.
    For a scout (or empty context): empty tuple -- scouts take no artifacts.

    Args:
        ctx: PhaseContext carrying executor_artifacts, reviewer_prompt,
             and reviewer_target for the subagent.
    """
    if ctx.executor_artifacts:
        return tuple(ctx.executor_artifacts)

    if ctx.reviewer_prompt or ctx.reviewer_target:
        # Charter-specific upstream set mirrors the read directives in reviewer.py.
        # milestones.md (for PLAN_REVIEWER) is living and will not be injected --
        # it falls through select_immutable_handovers into the listing.
        upstream: tuple[str, ...] = ()
        if ctx.reviewer_prompt == "TECH_PLAN_REVIEWER":
            upstream = ("core-flows.md",)
        elif ctx.reviewer_prompt == "PLAN_REVIEWER":
            upstream = ("tech-plan.md", "milestones.md")
        elif ctx.reviewer_prompt == "MILESTONE_REVIEWER":
            upstream = ("tech-plan.md",)
        return ("brief.md",) + upstream

    return ()


def preseed_pending_artifacts(agent: AgentState, app_state: AppState) -> None:
    """Drain pending_artifacts and pre-seed each as a <handoff_artifact> message.

    Drain-read-wrap-append-mark cycle:
      1. Copy agent.pending_artifacts and clear it.
      2. Resolve run_dir from phase_ctx, agent.run_dir, or app_state.run.run_dir.
      3. For each name not already in agent.injected_artifacts:
           - FileNotFoundError: skip silently, do NOT mark injected (producer
             phase may have been yield-skipped; absence is not an error).
           - Other OSError: inject a visible error placeholder and mark injected
             (a genuine I/O fault must never be hidden silently).
           - Success: wrap content in the <handoff_artifact> envelope and inject.
      4. Each injected message is appended to agent.message_history as its own
         ModelRequest(parts=[UserPromptPart(content=...)]) -- append-only to
         preserve the cached prompt prefix.

    Args:
        agent: The AgentState whose pending_artifacts queue is drained.
        app_state: The AppState supplying the run_dir fallback.
    """
    pending = list(agent.pending_artifacts)
    agent.pending_artifacts.clear()

    if not pending:
        return

    # Resolve run_dir with fallback chain: phase context -> agent field -> run state.
    run_dir: str = (
        (agent.phase_ctx.run_dir if agent.phase_ctx else "")
        or agent.run_dir
        or app_state.run.run_dir
        or ""
    )

    for name in pending:
        # Defensive dedup: select_immutable_handovers already filters, but guard
        # here too in case pending_artifacts is populated via other paths in future.
        if name in agent.injected_artifacts:
            continue

        path = Path(run_dir) / name if run_dir else Path(name)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            # Absent artifact -- producer phase may have been yield-skipped.
            # Skip silently and do NOT mark injected so the name stays available
            # for a future attempt if the file appears later.
            continue
        except OSError as exc:
            # Genuine I/O fault -- inject a visible error placeholder so the gap
            # is never silently hidden from the agent.
            text = format_handoff_message(name, f"(error reading artifact: {exc})", error=True)
            agent.message_history.append(ModelRequest(parts=[UserPromptPart(content=text)]))
            agent.injected_artifacts.add(name)
            continue

        text = format_handoff_message(name, content)
        agent.message_history.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        agent.injected_artifacts.add(name)


def reset_phase_context(agent: AgentState) -> None:
    # Clear the agent's accumulated conversation and all injection-dedup /
    # pending state at phase entry, so the next phase rebuilds a minimal
    # context (artifacts + listing + guidance) instead of accumulating on top
    # of the prior phase. The system prompt is delivered as pydantic-ai
    # instructions (re-applied to every request), not as a SystemPromptPart in
    # history, so clearing message_history does not drop it. injected_artifacts
    # MUST be cleared too, or select_immutable_handovers would dedup the
    # required artifacts away and the fresh context would receive none.
    agent.message_history = []
    agent.injected_artifacts.clear()
    agent.injected_context_files.clear()
    agent.pending_context_files.clear()
    agent.pending_artifacts.clear()
    agent.pending_listing = None


def preseed_pending_listing(agent: AgentState) -> None:
    # Drain pending_listing and append it as its own read-on-demand user
    # message, after the handover-artifact messages and before the step
    # guidance. A no-op when pending_listing is empty/None. Appended as a
    # distinct ModelRequest(UserPromptPart) to keep it a separate message from
    # the artifacts and the guidance for per-message cache locality.
    listing = agent.pending_listing
    agent.pending_listing = None
    if not listing:
        return
    agent.message_history.append(ModelRequest(parts=[UserPromptPart(content=listing)]))


def apply_artifact_cache_point(agent: AgentState, target_index: int) -> None:
    """Attach the ``cache_artifacts`` long-TTL CachePoint to a preseeded message.

    Realizes the ``cache_artifacts`` semantic breakpoint by attaching a
    long-TTL ``pydantic_ai.messages.CachePoint`` to the artifact/listing
    message at ``target_index`` -- the message the preseeds appended this turn.
    The CachePoint is appended to the ``UserPromptPart.content`` list so it
    becomes ``[<original str>, CachePoint(ttl='1h')]``, giving the stable
    artifact region its own long-lived cache breakpoint distinct from the
    churny conversation tail (which carries the short TTL via the settings-key
    ``anthropic_cache`` / ``bedrock_cache_messages``).

    Role gate: only long-tier agents (orchestrator/executor) receive the long
    artifact CachePoint, via ``cache_tier_for_role``.  Scouts/reviewers are
    single-shot and never benefit from a 1h TTL, so this is a no-op for them.

    No-op conditions (all return without attaching):

      - ``target_index < 0``: the caller's sentinel meaning "no message was
        preseeded this turn" (turns 2+ within a phase).
      - ``target_index >= len(agent.message_history)``: out of range.
      - ``cache_tier_for_role(agent.role) != "long"``: short-tier agent.
      - ``cache_ttl_for(agent.provider, "long") is None``: provider has no
        koan-managed explicit cache (e.g. google/openai, or unset in tests).
      - The target message is not a ``ModelRequest`` whose last part is a
        ``UserPromptPart`` whose ``content`` is a plain ``str``.  The
        plain-``str`` check is also the idempotency guard: if ``content`` is
        already a list, a CachePoint was attached on a prior call to the same
        object, so return (no double-append, preserving byte-stability).

    .. warning::

        The ``target_index`` is passed by the caller (the agent loop) and
        MUST NOT be re-derived as ``message_history[-1]``.  On turns 2+,
        ``[-1]`` points at the churny tail (a ``ModelResponse``, a tool-return
        ``ModelRequest``, or a steering/user ``ModelRequest``), and attaching
        the long TTL there would invert the initiative's goal.  The loop passes
        the sentinel ``-1`` on all non-phase-entry turns so this helper is a
        no-op then; the CachePoint placed on turn 1 rides forward at the fixed
        artifact boundary via ``all_messages()``.

    A CachePoint may not be the first content in a user message (transport
    constraint on Anthropic and Bedrock), so it attaches to the existing text
    rather than appending a bare CachePoint-only message.

    Args:
        agent: The AgentState whose message_history contains the target.
        target_index: Index of the last message the preseeds appended this
            turn, or ``-1`` (sentinel) when nothing was preseeded.
    """
    # Sentinel / out-of-range: nothing to attach to (turns 2+ pass -1).
    if target_index < 0 or target_index >= len(agent.message_history):
        return

    # Role gate: only long-tier agents get the long artifact CachePoint.
    if cache_tier_for_role(agent.role) != "long":
        return

    # Provider must have a koan-managed explicit cache (anthropic/bedrock).
    ttl = cache_ttl_for(agent.provider or "", "long")
    if ttl is None:
        return

    target = agent.message_history[target_index]
    # Only attach to a ModelRequest whose last part is a str-content
    # UserPromptPart -- the exact shape the preseeds produce.  The str check
    # is also the idempotency guard: a list means a CachePoint was already
    # attached on a prior call to this same object.
    if not isinstance(target, ModelRequest):
        return
    if not target.parts:
        return
    last_part = target.parts[-1]
    if not isinstance(last_part, UserPromptPart):
        return
    if not isinstance(last_part.content, str):
        return

    # Attach: rebuild the ModelRequest with content [original_str, CachePoint].
    # The CachePoint is a separate marker appended to the content list, not a
    # mutation of the existing text bytes (byte-stability invariant #161).
    new_parts = list(target.parts[:-1])
    new_parts.append(
        UserPromptPart(content=[last_part.content, CachePoint(ttl=ttl)])
    )
    agent.message_history[target_index] = ModelRequest(parts=new_parts)
