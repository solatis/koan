# In-process built-in tool implementations.
#
# Provides read/write/edit/glob/grep/bash as a PydanticAI FunctionToolset.
# Output formats mirror koan/agents/claude.py's parser spec so the metrics
# parser in spawn_subagent's fan-out works unchanged.
#
# read  -- anchored line output: "{number}\t{anchor}§{line}" (see line_anchors.py)
#          -> _parse_read_result: {lines_read, bytes_read}
#          edit references the anchor instead of an exact string match.
# grep  -- "Found N matches in M files" header + match lines
#          -> _parse_grep_result: {matches, files_matched}
# glob  -- "Found N files" header + one path per line
#          -> _parse_grep_result (fallback): {matches, files_matched}
# write/edit/bash: metrics=None (no parse target in the fold)
#
# Path-scope: write and edit self-validate the resolved path against the
# calling role and run_dir. Planning roles (intake/orchestrator/planner/scout)
# are confined to run_dir; the executor role may write anywhere in the project
# tree. A planning-role write outside run_dir returns a recoverable error string
# rather than raising, so the LLM can self-correct. koan/lib/permissions.py was
# deleted in M1; this path-scope logic lives tool-internally -- a central gate
# cannot express argument-level constraints.
#
# Context-file injection: path-bearing tools (read/write/edit/glob/grep)
# record their resolved paths into deps.agent.pending_context_files via
# _record_path_for_context_injection. Bash is exempt (no single path arg).
#
# write/edit/glob/grep/bash complete the built-in toolset (M4).
# web_search/web_fetch (M7): implemented locally (DuckDuckGo + httpx) below.

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .line_anchors import apply_anchored_edit, render_anchored

if TYPE_CHECKING:
    from .koan_tools import ToolDeps


# Planning roles are confined to run_dir for write/edit operations.
# Defined here (not imported) because koan/lib/permissions.py was deleted in M1.
_PLANNING_ROLES: frozenset[str] = frozenset({
    "intake",
    "orchestrator",
    "planner",
    "scout",
})


# -- Path helpers ------------------------------------------------------------- #


def _resolve_path(file_path: str, deps: Any) -> Path:
    """Resolve file_path to an absolute Path using the agent's run_dir as base.

    Relative paths are anchored to run_dir (when available) so agents that
    receive relative paths from the model still resolve to the correct location.
    """
    p = Path(file_path)
    if p.is_absolute():
        return p
    run_dir = getattr(getattr(deps, "agent", None), "run_dir", None)
    if run_dir:
        return Path(run_dir) / file_path
    return Path.cwd() / file_path


def _path_scope_violation(deps: Any, resolved_path: Path) -> str | None:
    """Return an error message when a planning role writes outside run_dir.

    Planning roles (intake/orchestrator/planner/scout) may only write inside
    run_dir; the executor role may write anywhere. When run_dir is empty, the
    check is skipped (permissive degradation -- run_dir is set in all real runs).
    Never raises; returns None when the write is permitted.

    Args:
        deps: ToolDeps carrying AgentState (deps.agent.role, deps.agent.run_dir).
        resolved_path: The absolute Path that would be written.

    Returns:
        None when the write is permitted; a human-readable violation string
        when the path is outside run_dir for a confined planning role.
    """
    role = getattr(getattr(deps, "agent", None), "role", "")
    if role not in _PLANNING_ROLES:
        return None
    run_dir = getattr(getattr(deps, "agent", None), "run_dir", None)
    if not run_dir:
        return None
    resolved = resolved_path.resolve()
    resolved_run = Path(run_dir).resolve()
    try:
        resolved.relative_to(resolved_run)
        return None
    except ValueError:
        return (
            f"path-scope violation: role {role!r} may only write inside"
            f" run_dir {run_dir!r}; got {str(resolved_path)!r}."
            " Write to a path inside run_dir instead."
        )


def _record_path_for_context_injection(deps: Any, resolved_path: Path) -> None:
    """Queue any new context files found on the path up to project_root.

    Calls walk_for_context_files and appends the results (deduped) to
    deps.agent.pending_context_files so the history processor injects them
    before the next model request.

    Skips silently when project_root or the agent state is unavailable.

    Args:
        deps: ToolDeps with app_state and agent.
        resolved_path: Absolute Path just accessed by a file tool.
    """
    from .context_files import walk_for_context_files

    agent = getattr(deps, "agent", None)
    if agent is None:
        return
    project_root = getattr(getattr(deps, "app_state", None), "run", None)
    project_root = getattr(project_root, "project_dir", "") if project_root else ""
    if not project_root:
        return

    new_files = walk_for_context_files(
        str(resolved_path),
        project_root,
        agent.injected_context_files,
    )
    pending = set(agent.pending_context_files)
    for f in new_files:
        if f not in pending and f not in agent.injected_context_files:
            agent.pending_context_files.append(f)
            pending.add(f)


# -- Tool implementations ----------------------------------------------------- #


async def read_tool(
    ctx: Any,
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    enforce_limits: bool = True,
) -> str:
    """Read a file and return its contents in anchored line format.

    Each output line is `{lineno}\\t{anchor}{ANCHOR_DELIMITER}{content}` where
    the anchor can be copied into edit_tool to target that line. Anchors are
    computed over the whole file so a slice's anchors resolve at edit time.

    The output format preserves the `{digit}\\t` prefix that
    _parse_read_result_from_content keys on, so lines_read metrics stay correct.

    Path resolution is relative to run_dir when available. After reading,
    the resolved path is recorded for just-in-time context-file injection.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        file_path: Absolute or relative path to read.
        offset: 0-based line offset to start reading from (default 0).
        limit: Maximum number of lines to return (default 2000).
        enforce_limits: When True (default), reject results exceeding the size
            ceiling. Set to False only by trusted wrappers (e.g. koan_artifact_read
            in Milestone 3) that are exempt from the untrusted-tool reject ceiling.
            Never expose this parameter to the model-facing registered read tool.
    """
    deps = getattr(ctx, "deps", None)
    resolved = _resolve_path(file_path, deps)

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading {file_path}: {e}"

    # Record for context-file injection after a successful read.
    if deps is not None:
        _record_path_for_context_injection(deps, resolved)

    # Anchored output: "{lineno}\t{anchor}§{content}". The anchor lets edit
    # target this line without exact-string-match (see docs/tools.md).
    rendered = render_anchored(content, offset, limit)
    return _enforce_output_limits(rendered) if enforce_limits else rendered


async def write_tool(ctx: Any, file_path: str, content: str) -> str:
    """Create or overwrite a file with the given content.

    Enforces path-scope: planning roles (intake/orchestrator/planner/scout)
    may only write inside run_dir; executors may write the full project tree.
    A planning-role write outside run_dir returns a recoverable "Error: ..."
    string rather than raising, so the LLM can self-correct.
    After writing, the resolved path is recorded for context-file injection.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        file_path: Absolute or relative path to create/overwrite.
        content: Full content to write to the file.
    """
    deps = getattr(ctx, "deps", None)
    resolved = _resolve_path(file_path, deps)

    if deps is not None:
        violation = _path_scope_violation(deps, resolved)
        if violation is not None:
            return f"Error: {violation}"

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error writing {file_path}: {e}"

    if deps is not None:
        _record_path_for_context_injection(deps, resolved)

    return f"Wrote {len(content)} bytes to {file_path}"


async def edit_tool(
    ctx: Any,
    file_path: str,
    anchor: str,
    text: str,
    end_anchor: str | None = None,
    edit_type: str = "replace",
) -> str:
    """Edit a file by anchored line reference (see docs/tools.md).

    The anchor is copied from a `read` -- `{8-hex}{ANCHOR_DELIMITER}{line text}` --
    giving a precise location plus drift verification, instead of exact-string-match.
    Enforces path-scope for planning roles; an out-of-run_dir write returns a
    recoverable "Error: ..." string rather than raising. After editing, the
    resolved path is recorded for context-file injection.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        file_path: Absolute or relative path to edit.
        anchor: The anchor token of the target line (`{anchor}{ANCHOR_DELIMITER}{line}` from read).
        text: Replacement / inserted content (split on newlines; empty deletes).
        end_anchor: Optional second anchor for an inclusive multi-line replace range.
        edit_type: "replace" (default), "insert_before", or "insert_after".
    """
    deps = getattr(ctx, "deps", None)
    resolved = _resolve_path(file_path, deps)

    if deps is not None:
        violation = _path_scope_violation(deps, resolved)
        if violation is not None:
            return f"Error: {violation}"

    try:
        existing = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading {file_path}: {e}"

    updated, err = apply_anchored_edit(existing, anchor, text, end_anchor, edit_type)
    if err:
        return f"Error: {err}"

    try:
        resolved.write_text(updated, encoding="utf-8")
    except OSError as e:
        return f"Error writing {file_path}: {e}"

    if deps is not None:
        _record_path_for_context_injection(deps, resolved)

    return f"Edited {file_path} ({edit_type})"


# -- Search scoping + output limits ------------------------------------------- #
#
# glob/grep recurse with "**/*", which pathlib walks into dependency, build, and
# VCS directories (the koan repo's own .env/ venv is ~34k files, node_modules and
# __pycache__ tens of thousands more). Unfiltered, a single grep reads megabytes
# of irrelevant content and the next model request exceeds the provider's
# input-token limit (Gemini rejects requests over ~1M tokens). These guards keep
# search results scoped to source and bound any single tool result's size.

_IGNORED_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__",
    ".venv", ".env", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".cache", ".idea", ".vscode",
})

# Hard ceilings on a single tool result. A read/grep/glob/bash result that
# exceeds either limit is REJECTED with an error rather than truncated, so no
# single call can inflate the conversation history toward the provider's
# input-token ceiling. Erroring forces the model to narrow the call (tighter
# grep pattern, read offset/limit, scoped bash) before any content lands in
# history. Conservative by default.
_MAX_TOOL_OUTPUT_LINES: int = 500
_MAX_TOOL_OUTPUT_BYTES: int = 10_000


def _is_ignored(path: Path, root: Path) -> bool:
    """True when *path* sits under an ignored directory component below *root*.

    The check is on the path's components relative to the search root, so an
    explicit search rooted inside an ignored directory (e.g. path=node_modules/x)
    is still honoured -- only recursion that descends INTO an ignored subdir from
    a higher root is skipped.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return any(part in _IGNORED_DIRS for part in rel.parts)


def _enforce_output_limits(text: str) -> str:
    """Return *text* unchanged, or an error message when it is too large to inject.

    A tool result is rejected (not truncated) when it exceeds either ceiling:
      - more than _MAX_TOOL_OUTPUT_LINES lines, or
      - _MAX_TOOL_OUTPUT_BYTES bytes or more (UTF-8 encoded).

    Returning an error -- rather than a truncated prefix -- keeps the running
    history small: no partial content lands, and the model gets an actionable
    message telling it how to narrow the call so the retry fits.
    """
    n_bytes = len(text.encode("utf-8"))
    n_lines = len(text.splitlines())
    if n_lines <= _MAX_TOOL_OUTPUT_LINES and n_bytes < _MAX_TOOL_OUTPUT_BYTES:
        return text
    reasons: list[str] = []
    if n_lines > _MAX_TOOL_OUTPUT_LINES:
        reasons.append(f"{n_lines} lines (limit {_MAX_TOOL_OUTPUT_LINES})")
    if n_bytes >= _MAX_TOOL_OUTPUT_BYTES:
        reasons.append(f"{n_bytes} bytes (limit {_MAX_TOOL_OUTPUT_BYTES})")
    return (
        f"Error: tool result too large -- {', '.join(reasons)}. The result was "
        "not returned, to keep the context budget intact. Narrow the call and "
        "retry: use a tighter grep pattern or glob, read a slice with "
        "offset/limit, or scope the bash command (e.g. head, specific paths)."
    )


async def glob_tool(ctx: Any, pattern: str, path: str | None = None) -> str:
    """Find files matching a glob pattern.

    Returns a "Found N files" header followed by one matching path per line.
    The header format lets _parse_grep_result in koan/agents/claude.py derive
    {matches, files_matched} metrics -- glob matches are file-per-match since
    each path IS the match. Ignored directories (e.g. .git, node_modules, .venv)
    are excluded to keep results focused on source. Results are rejected with an
    error when they exceed the size ceiling. After listing, the search root is
    recorded for context-file injection.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        pattern: Glob pattern to match, e.g. "**/*.py".
        path: Optional directory to search in (defaults to run_dir or cwd).
    """
    deps = getattr(ctx, "deps", None)
    if path is not None:
        search_root = _resolve_path(path, deps)
    else:
        run_dir = getattr(getattr(deps, "agent", None), "run_dir", None) if deps else None
        search_root = Path(run_dir) if run_dir else Path.cwd()

    try:
        matches = sorted(
            str(p) for p in search_root.glob(pattern)
            if not _is_ignored(p, search_root)
        )
    except Exception as e:
        return f"Error running glob {pattern!r} in {search_root}: {e}"

    n = len(matches)
    # Format: "Found N files" header that _parse_grep_result recognises.
    # Each file is its own match, so files_matched == matches.
    header = f"Found {n} files"
    if n == 0:
        result = header
    else:
        result = header + "\n" + "\n".join(matches)

    if deps is not None:
        _record_path_for_context_injection(deps, search_root)

    return _enforce_output_limits(result)


async def grep_tool(
    ctx: Any,
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
) -> str:
    """Search file contents for a regex pattern.

    Emits a "Found N matches in M files" header followed by matching lines in
    "file:line_number:content" format. The header is what _parse_grep_result in
    koan/agents/claude.py expects to derive {matches, files_matched} metrics.
    Ignored directories (e.g. .git, node_modules, .venv) are excluded from the
    candidate file set. Results are rejected with an error when they exceed the
    size ceiling.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        pattern: Regular-expression pattern to search for.
        path: Directory or file to search in (defaults to run_dir or cwd).
        glob: Optional glob pattern to filter which files are searched.
    """
    deps = getattr(ctx, "deps", None)
    if path is not None:
        search_root = _resolve_path(path, deps)
    else:
        run_dir = getattr(getattr(deps, "agent", None), "run_dir", None) if deps else None
        search_root = Path(run_dir) if run_dir else Path.cwd()

    # Collect candidate files.
    if search_root.is_file():
        candidates = [search_root]
    else:
        file_glob = glob if glob else "**/*"
        try:
            candidates = [
                p for p in search_root.glob(file_glob)
                if p.is_file() and not _is_ignored(p, search_root)
            ]
        except Exception as e:
            return f"Error finding files for grep in {search_root}: {e}"

    # Search each file.
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid pattern {pattern!r}: {e}"

    match_lines: list[str] = []
    files_with_matches: set[str] = set()

    for candidate in sorted(candidates):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                match_lines.append(f"{candidate}:{lineno}:{line}")
                files_with_matches.add(str(candidate))

    n_matches = len(match_lines)
    n_files = len(files_with_matches)
    header = f"Found {n_matches} matches in {n_files} files"

    if n_matches == 0:
        result = header
    else:
        result = header + "\n" + "\n".join(match_lines)

    if deps is not None:
        _record_path_for_context_injection(deps, search_root)

    return _enforce_output_limits(result)


async def bash_tool(
    ctx: Any,
    command: str,
    timeout: int | None = None,
) -> str:
    """Execute a shell command and return stdout + stderr combined.

    No sandbox is applied -- keep the current permission posture. Bash is
    exempt from context-file injection (no single canonical path argument).
    Results are rejected with an error when they exceed the size ceiling.

    For the orchestrator role, a call-time phase gate is applied: bash is only
    allowed in the phases listed in _ORCHESTRATOR_BASH_PHASES. A wrong-phase
    call returns a recoverable "Error: ..." string. Non-orchestrator roles
    (executor, scout, reviewer) always run bash regardless of phase.

    Args:
        ctx: PydanticAI RunContext with ToolDeps as deps.
        command: Shell command to execute.
        timeout: Optional timeout in seconds (default None = no limit).
    """
    deps = getattr(ctx, "deps", None)

    # Call-time phase gate for orchestrator; non-orchestrators short-circuit to None.
    from .tool_policy import build_tool_policy, phase_gate_message
    role = getattr(getattr(deps, "agent", None), "role", "") if deps else ""
    phase = getattr(getattr(getattr(deps, "app_state", None), "run", None), "phase", "") or ""
    gate_msg = phase_gate_message(build_tool_policy(), role, phase, "bash")
    if gate_msg is not None:
        return f"Error: {gate_msg}"

    run_dir = getattr(getattr(deps, "agent", None), "run_dir", None) if deps else None
    cwd = run_dir or None

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        combined = result.stdout
        if result.stderr:
            combined = combined + result.stderr if combined else result.stderr
        if result.returncode != 0:
            combined = f"Exit code: {result.returncode}\n{combined}"
        return _enforce_output_limits(combined) if combined else ""
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s: {command}"
    except Exception as e:
        return f"Error running command: {e}"


# -- web tools (M7) ----------------------------------------------------------- #
# Implemented locally (DuckDuckGo search + httpx fetch) rather than via each
# provider's native builtin web tool. A local implementation is portable across
# all four providers (Bedrock has no native web search) and -- unlike a
# provider-side builtin -- runs as an ordinary koan function tool, so its result
# flows through the same StreamEvent/projection path as the other built-ins.


def _strip_html(html: str) -> str:
    """Reduce an HTML document to readable text (drop script/style + tags)."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


async def web_search_tool(ctx: Any, query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo and return ranked results.

    Args:
        ctx: PydanticAI RunContext (unused; kept for signature uniformity).
        query: Search query string.
        max_results: Maximum number of results to return (default 5).
    """
    import asyncio

    def _search() -> list[dict]:
        from ddgs import DDGS
        with DDGS() as client:
            return list(client.text(query, max_results=max_results))

    try:
        results = await asyncio.to_thread(_search)
    except Exception as e:
        return f"Error: web search failed: {e}"

    if not results:
        return f"No results for: {query}"

    lines = [f"Found {len(results)} result(s) for: {query}", ""]
    for i, r in enumerate(results, 1):
        title = r.get("title") or r.get("name") or ""
        href = r.get("href") or r.get("url") or ""
        body = r.get("body") or r.get("snippet") or ""
        lines.append(f"{i}. {title}\n   {href}\n   {body}")
    return "\n".join(lines)


async def web_fetch_tool(ctx: Any, url: str, max_chars: int = 20000) -> str:
    """Fetch a URL and return its text content (HTML stripped to readable text).

    Args:
        ctx: PydanticAI RunContext (unused; kept for signature uniformity).
        url: The URL to fetch.
        max_chars: Truncate the returned text to this many characters.
    """
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url, headers={"User-Agent": "koan/1.0"})
            resp.raise_for_status()
            body = resp.text
            ctype = resp.headers.get("content-type", "")
    except Exception as e:
        return f"Error: fetch failed for {url}: {e}"

    text = _strip_html(body) if "html" in ctype.lower() else body
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"
    return text


# -- Toolset builder ---------------------------------------------------------- #


def build_builtin_toolset() -> Any:
    """Build the built-in FunctionToolset with all built-in tools registered.

    Registers read, write, edit, glob, grep, bash (M4) and web_search,
    web_fetch (M7, local DuckDuckGo + httpx).

    Each tool is wrapped in a thin inner function without a RunContext type
    annotation: 'from __future__ import annotations' makes annotations
    into strings, which pydantic_ai's schema generation cannot resolve for
    RunContext[...]. Omitting the annotation lets pydantic_ai detect the
    context parameter via takes_ctx=True.

    Returns a FunctionToolset[ToolDeps] with all built-in tools registered
    under their canonical lowercase names so KOAN_MCP_TOOLS and the
    spawn_subagent fan-out recognise them.
    """
    from pydantic_ai.toolsets.function import FunctionToolset

    ts: FunctionToolset[Any] = FunctionToolset()

    # -- read ------------------------------------------------------------------
    # enforce_limits is intentionally absent from _read's signature -- the model-
    # facing built-in read ALWAYS enforces the ceiling. Only trusted wrappers
    # (e.g. koan_artifact_read in M3) call read_tool directly with enforce_limits=False.
    async def _read(ctx, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file and return anchored, line-numbered content for precise editing."""
        return await read_tool(ctx, file_path, offset, limit)

    ts.add_function(
        _read,
        takes_ctx=True,
        name="read",
        description=(
            "Read a file from the local filesystem. Each line is returned as "
            "{line_number}\\t{anchor}§{content}. Copy an anchor (the "
            "{anchor}§{content} part) into the edit tool to change that line. "
            "Use offset and limit to read large files in pages."
        ),
    )

    # -- write -----------------------------------------------------------------
    async def _write(ctx, file_path: str, content: str) -> str:
        """Create or overwrite a file with the given content."""
        return await write_tool(ctx, file_path, content)

    ts.add_function(
        _write,
        takes_ctx=True,
        name="write",
        description=(
            "Create or overwrite a file with the given content. "
            "Planning roles (orchestrator/scout/planner/intake) are confined to run_dir; "
            "the executor role may write anywhere in the project tree."
        ),
    )

    # -- edit ------------------------------------------------------------------
    async def _edit(
        ctx,
        file_path: str,
        anchor: str,
        text: str,
        end_anchor: str | None = None,
        edit_type: str = "replace",
    ) -> str:
        """Edit a file by anchored line reference (anchor copied from read)."""
        return await edit_tool(ctx, file_path, anchor, text, end_anchor, edit_type)

    ts.add_function(
        _edit,
        takes_ctx=True,
        name="edit",
        description=(
            "Edit a file by anchored line reference. Read the file first; copy the "
            "target line's anchor token ({anchor}§{line text}) into `anchor`. "
            "edit_type='replace' (default) replaces that line, or the inclusive "
            "range [anchor, end_anchor] when end_anchor is given; empty `text` "
            "deletes. 'insert_before'/'insert_after' insert `text` at the anchor. "
            "If an anchor is not found, re-read the file for current anchors."
        ),
    )

    # -- glob ------------------------------------------------------------------
    async def _glob(ctx, pattern: str, path: str | None = None) -> str:
        """Find files matching a glob pattern in a directory."""
        return await glob_tool(ctx, pattern, path)

    ts.add_function(
        _glob,
        takes_ctx=True,
        name="glob",
        description=(
            "Find files matching a glob pattern (e.g. '**/*.py'). "
            "Returns a summary header and the list of matching paths."
        ),
    )

    # -- grep ------------------------------------------------------------------
    async def _grep(
        ctx,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> str:
        """Search file contents for a regular-expression pattern."""
        return await grep_tool(ctx, pattern, path, glob)

    ts.add_function(
        _grep,
        takes_ctx=True,
        name="grep",
        description=(
            "Search file contents for a regular-expression pattern. "
            "Returns a 'Found N matches in M files' summary plus matching lines. "
            "Use the glob parameter to filter which files are searched."
        ),
    )

    # -- bash ------------------------------------------------------------------
    async def _bash(ctx, command: str, timeout: int | None = None) -> str:
        """Execute a shell command and return stdout + stderr combined."""
        return await bash_tool(ctx, command, timeout)

    ts.add_function(
        _bash,
        takes_ctx=True,
        name="bash",
        description=(
            "Execute a shell command and return combined stdout + stderr. "
            "No sandbox is applied. Optionally specify a timeout in seconds."
        ),
    )

    # -- web_search (M7) -------------------------------------------------------
    async def _web_search(ctx, query: str, max_results: int = 5) -> str:
        """Search the web (DuckDuckGo) and return ranked results."""
        return await web_search_tool(ctx, query, max_results)

    ts.add_function(
        _web_search,
        takes_ctx=True,
        name="web_search",
        description=(
            "Search the web via DuckDuckGo. Returns a ranked list of "
            "title / URL / snippet results. Args: query, max_results (default 5)."
        ),
    )

    # -- web_fetch (M7) --------------------------------------------------------
    async def _web_fetch(ctx, url: str, max_chars: int = 20000) -> str:
        """Fetch a URL and return its text content (HTML stripped)."""
        return await web_fetch_tool(ctx, url, max_chars)

    ts.add_function(
        _web_fetch,
        takes_ctx=True,
        name="web_fetch",
        description=(
            "Fetch a URL and return its readable text content (HTML tags "
            "stripped). Args: url, max_chars (truncation limit, default 20000)."
        ),
    )

    return ts
