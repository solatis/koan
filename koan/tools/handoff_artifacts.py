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
from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelRequest, UserPromptPart

from .artifact_registry import LIVING_DOC_FAMILIES, parse_artifact_filename

if TYPE_CHECKING:
    from ..phases import PhaseContext
    from ..state import AgentState, AppState


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


def subagent_candidates(ctx: "PhaseContext") -> tuple[str, ...]:
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


def preseed_pending_artifacts(agent: "AgentState", app_state: "AppState") -> None:
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
