# Context-file discovery, walk, formatting, and just-in-time injection.
#
# Discovers AGENTS.md / CLAUDE.md context files in a project tree and injects
# them as standalone <project_instructions> user messages via a pydantic-ai
# ProcessHistory capability registered on the agent. Injection is just-in-time:
# the project-directory file is seeded at loop start; subtree files are queued
# on the first tool-touch of any path in that subtree.
#
# Precedence: AGENTS.md > CLAUDE.md (per brief decision 14).
# Walk stops at project_root -- never above it.
# @-imports inside context files are opaque (not expanded).
# Per-agent dedup via AgentState.injected_context_files.
# Bash tool is exempt (no single canonical path argument).
#
# NOTE: Do NOT add 'from __future__ import annotations' to this module.
# The _inject_context_files inner function uses a RunContext annotation that
# must resolve at definition time (not as a deferred string) so that
# pydantic_ai._utils.takes_run_context correctly detects the context
# parameter and calls the processor with (ctx, messages) instead of (messages,).

import os
from pathlib import Path
from typing import Any


# Ordered list of candidate context-file names; AGENTS.md beats CLAUDE.md.
_CONTEXT_FILE_NAMES = ("AGENTS.md", "CLAUDE.md")


def discover_context_file(directory: str) -> str | None:
    """Return the absolute path of the context file for a directory, or None.

    Checks for AGENTS.md first, then CLAUDE.md. Returns the first one that
    exists as a regular file. Returns None when neither is present.

    Args:
        directory: Absolute path to the directory to inspect.
    """
    for name in _CONTEXT_FILE_NAMES:
        candidate = Path(directory) / name
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def walk_for_context_files(
    touched_path: str,
    project_root: str,
    injected: set,
) -> list[str]:
    """Walk from touched_path up to project_root, returning new context files.

    Starting at the directory containing touched_path, ascend toward project_root
    one directory at a time. At each level, check for a context file
    (AGENTS.md > CLAUDE.md). Stop ascending at the first level whose context
    file is already in injected (that level and above are already covered), and
    never go above project_root.

    Returns the discovered not-yet-injected paths in bottom-up order (deepest
    first) so the history processor injects them in discovery order.

    @-imports inside context files are treated as opaque text and are not
    followed -- the walk is purely directory-tree based.

    Args:
        touched_path: Absolute path to a file or directory that was accessed.
        project_root: The project root; walk never ascends beyond this boundary.
        injected: Set of absolute paths already injected; used to stop early.
    """
    if not project_root:
        return []

    root = Path(project_root).resolve()
    start = Path(touched_path).resolve()
    # Start from the file's directory (or the directory itself if it is one).
    current = start if start.is_dir() else start.parent

    # Walk upward collecting context files that haven't been injected yet.
    # Stop at the first already-injected ancestor OR when we exceed project_root.
    results: list[str] = []
    while True:
        try:
            # is_relative_to ensures we never escape the project root.
            current.relative_to(root)
        except ValueError:
            break

        ctx_file = discover_context_file(str(current))
        if ctx_file is not None:
            if ctx_file in injected:
                # This level is already covered; everything above is too.
                break
            results.append(ctx_file)

        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return results


def format_context_message(path: str, content: str) -> str:
    """Wrap context-file content in a <project_instructions> envelope.

    The envelope is placed inside a <system-reminder> block so it is rendered
    consistently with the driver's existing reminder convention (e.g. CLAUDE.md
    injection in the original SDK path). The path attribute lets the model
    know which file the instructions came from.

    @-imports inside content are treated as opaque text and are not expanded.

    Args:
        path: Absolute path to the context file (used as the path attribute).
        content: Raw text content of the context file.
    """
    return (
        f"<system-reminder>\n"
        f"<project_instructions path={path!r}>\n"
        f"{content}\n"
        f"</project_instructions>\n"
        f"</system-reminder>"
    )


def make_context_history_processor(deps: Any) -> Any:
    """Return a pydantic-ai HistoryProcessor that injects pending context files.

    The returned processor drains deps.agent.pending_context_files before each
    model request, reads each file, formats it as a <project_instructions> user
    message, appends it to both the live message history (ctx.messages) and the
    current request's message list, and records the path in
    deps.agent.injected_context_files to prevent duplicate injection.

    Files already in injected_context_files are silently skipped. Read errors
    are silently skipped so a missing context file never blocks the run.

    The processor uses the with-RunContext async signature:
        async (ctx: RunContext, messages: list[ModelMessage]) -> list[ModelMessage]
    pydantic_ai._utils.takes_run_context detects the context parameter by
    inspecting the annotation of the first parameter. The annotation must resolve
    to the actual RunContext class at definition time -- NOT a deferred string
    (which is why this module has no 'from __future__ import annotations'). We
    import RunContext inside this function so it is in scope when _inject_context_files
    is defined, ensuring the annotation object is RunContext itself (not a string).

    Args:
        deps: ToolDeps carrying the AgentState (deps.agent) for the agent whose
              context files should be injected.
    """
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    # Import RunContext here (not at module level) so it is in scope when
    # _inject_context_files' annotations are evaluated at definition time.
    # takes_run_context inspects the annotation of the first parameter to
    # decide whether to pass (ctx, messages) or just (messages). Without the
    # actual RunContext class as the annotation value, it falls back to the
    # no-context form and the call fails with a missing-argument TypeError.
    from pydantic_ai.tools import RunContext

    async def _inject_context_files(ctx: RunContext, messages: list) -> list:
        """Drain pending_context_files and inject them as user messages.

        Appends each new context-file message to ctx.messages (the live
        message_history) so the injection persists for future requests within
        the same agent.iter() run. Also appends to messages (the per-request
        copy) so the current model request sees the context.
        """
        agent = deps.agent
        to_inject = list(agent.pending_context_files)
        agent.pending_context_files.clear()

        appended: list = []
        for file_path in to_inject:
            if file_path in agent.injected_context_files:
                continue
            try:
                content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                # Missing or unreadable context file; skip silently.
                continue
            text = format_context_message(file_path, content)
            msg = ModelRequest(parts=[UserPromptPart(content=text)])
            appended.append(msg)
            agent.injected_context_files.add(file_path)

        if not appended:
            return messages

        # Persist injected messages to the live history so subsequent model
        # requests (within the same agent.iter() run) still have the context
        # in their input sequence. ctx.messages IS the live message_history list.
        for msg in appended:
            ctx.messages.append(msg)

        return messages + appended

    return _inject_context_files
