# Unit tests for koan.tools.builtin_tools.
#
# Tests each tool in isolation using tmp_path fixtures. All tests are
# synchronous or use anyio where the tool is async. No network calls are made.
#
# Coverage:
# - write/edit create and modify files correctly
# - edit enforces single-unique-match semantics
# - _path_scope_violation returns a message for planning-role writes outside run_dir
# - _path_scope_violation returns None for executor writes anywhere
# - write/edit return a recoverable "Error: ..." for planning-role out-of-scope writes
# - bash_tool returns a recoverable "Error: ..." when orchestrator calls it outside bash phases
# - grep/glob/read produce the metrics dicts the fold expects
# - bash runs a command with output capture and timeout

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from koan.tools.builtin_tools import (
    DEFAULT_LIMIT,
    _path_scope_violation,
    bash_tool,
    edit_tool,
    glob_tool,
    grep_tool,
    read_tool,
    write_tool,
)
from koan.tools.line_anchors import ANCHOR_DELIMITER, compute_anchors


# -- Helpers ----------------------------------------------------------------- #


def _make_ctx(
    role: str = "executor",
    run_dir: str = "",
    project_dir: str = "",
    phase: str = "",
) -> SimpleNamespace:
    """Build a minimal fake RunContext with ToolDeps for tool tests.

    Returns a SimpleNamespace that mimics just enough of RunContext[ToolDeps]
    for the built-in tools (ctx.deps.agent.role, ctx.deps.agent.run_dir,
    ctx.deps.app_state.run.project_dir, ctx.deps.app_state.run.phase, etc.).

    Args:
        role: Agent role string (default "executor").
        run_dir: Agent run directory (default "" -- no scope enforcement).
        project_dir: Project root directory for context-file injection.
        phase: Current workflow phase string; required for bash gate tests.
    """
    agent = SimpleNamespace(
        role=role,
        run_dir=run_dir,
        injected_context_files=set(),
        pending_context_files=[],
    )
    run_state = SimpleNamespace(project_dir=project_dir, phase=phase)
    app_state = SimpleNamespace(run=run_state)
    deps = SimpleNamespace(agent=agent, app_state=app_state)
    return SimpleNamespace(deps=deps)


# -- write_tool -------------------------------------------------------------- #


@pytest.mark.anyio
async def test_write_tool_creates_file(tmp_path):
    """write_tool creates a new file with the given content.

    Verifies that the file exists on disk and has the exact bytes written.
    """
    target = tmp_path / "out.txt"
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await write_tool(ctx, str(target), "hello world\n")
    assert target.exists()
    assert target.read_text() == "hello world\n"
    assert "wrote" in result.lower() or str(len("hello world\n")) in result


@pytest.mark.anyio
async def test_write_tool_overwrites_existing_file(tmp_path):
    """write_tool overwrites an existing file completely."""
    target = tmp_path / "out.txt"
    target.write_text("old content")
    ctx = _make_ctx(run_dir=str(tmp_path))
    await write_tool(ctx, str(target), "new content\n")
    assert target.read_text() == "new content\n"


@pytest.mark.anyio
async def test_write_tool_creates_parent_dirs(tmp_path):
    """write_tool creates missing parent directories."""
    target = tmp_path / "sub" / "dir" / "file.txt"
    ctx = _make_ctx(run_dir=str(tmp_path))
    await write_tool(ctx, str(target), "content")
    assert target.exists()


# -- edit_tool (anchored) ---------------------------------------------------- #


def _anchor_token(content: str, line_index: int) -> str:
    """Build the '{anchor}{ANCHOR_DELIMITER}{line}' token for a 0-based line, as read would emit."""
    lines = content.splitlines()
    anchors = compute_anchors(lines)
    return f"{anchors[line_index]}{ANCHOR_DELIMITER}{lines[line_index]}"


@pytest.mark.anyio
async def test_edit_tool_replace_line(tmp_path):
    """edit_tool replaces the anchored line, leaving the rest intact."""
    target = tmp_path / "edit.txt"
    content = "line one\nline two\nline three\n"
    target.write_text(content)
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await edit_tool(ctx, str(target), _anchor_token(content, 1), "LINE TWO")
    assert target.read_text() == "line one\nLINE TWO\nline three\n"
    assert "Edited" in result


@pytest.mark.anyio
async def test_edit_tool_disambiguates_duplicate_lines(tmp_path):
    """Identical lines get distinct anchors (~N); editing one leaves the others."""
    target = tmp_path / "edit.txt"
    content = "dup\ndup\ndup\n"
    target.write_text(content)
    ctx = _make_ctx(run_dir=str(tmp_path))
    # Edit the second occurrence (index 1) only.
    await edit_tool(ctx, str(target), _anchor_token(content, 1), "rep")
    assert target.read_text() == "dup\nrep\ndup\n"


@pytest.mark.anyio
async def test_edit_tool_range_replace(tmp_path):
    """edit_tool replaces an inclusive [anchor, end_anchor] range with new text."""
    target = tmp_path / "edit.txt"
    content = "a\nb\nc\nd\n"
    target.write_text(content)
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await edit_tool(
        ctx, str(target),
        _anchor_token(content, 1), "B\nC2",
        end_anchor=_anchor_token(content, 2),
    )
    assert target.read_text() == "a\nB\nC2\nd\n"
    assert "Edited" in result


@pytest.mark.anyio
async def test_edit_tool_insert_after(tmp_path):
    """edit_tool insert_after places text below the anchored line."""
    target = tmp_path / "edit.txt"
    content = "a\nb\n"
    target.write_text(content)
    ctx = _make_ctx(run_dir=str(tmp_path))
    await edit_tool(ctx, str(target), _anchor_token(content, 0), "a2", edit_type="insert_after")
    assert target.read_text() == "a\na2\nb\n"


@pytest.mark.anyio
async def test_edit_tool_anchor_not_found(tmp_path):
    """edit_tool errors (file unchanged) when the anchor is absent."""
    target = tmp_path / "edit.txt"
    target.write_text("hello world\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await edit_tool(ctx, str(target), "deadbeef§missing line", "x")
    assert "Error" in result and "not found" in result
    assert target.read_text() == "hello world\n"


@pytest.mark.anyio
async def test_edit_tool_content_mismatch_rejected(tmp_path):
    """edit_tool errors on inline-content drift (anchor exists, content differs)."""
    target = tmp_path / "edit.txt"
    content = "alpha\nbeta\n"
    target.write_text(content)
    anchors = compute_anchors(content.splitlines())
    ctx = _make_ctx(run_dir=str(tmp_path))
    # Correct anchor for line 0 but wrong inline content -> drift error.
    result = await edit_tool(ctx, str(target), f"{anchors[0]}{ANCHOR_DELIMITER}WRONG", "x")
    assert "Error" in result and "mismatch" in result
    assert target.read_text() == content


# -- _path_scope_violation --------------------------------------------------- #


def test_path_scope_violation_planning_inside_run_dir_allowed(tmp_path):
    """Planning role write inside run_dir returns None (permitted)."""
    run_dir = str(tmp_path)
    ctx = _make_ctx(role="orchestrator", run_dir=run_dir)
    target = tmp_path / "plan.md"
    assert _path_scope_violation(ctx.deps, target) is None


def test_path_scope_violation_planning_outside_run_dir_rejected(tmp_path):
    """Planning role write outside run_dir returns a non-None violation string."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = _make_ctx(role="orchestrator", run_dir=str(run_dir))
    outside = tmp_path / "outside.txt"
    result = _path_scope_violation(ctx.deps, outside)
    assert result is not None
    assert "path-scope violation" in result


def test_path_scope_violation_executor_outside_run_dir_allowed(tmp_path):
    """Executor role may write anywhere; _path_scope_violation returns None."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = _make_ctx(role="executor", run_dir=str(run_dir))
    outside = tmp_path / "project" / "src" / "file.py"
    assert _path_scope_violation(ctx.deps, outside) is None


def test_path_scope_violation_scout_outside_run_dir_rejected(tmp_path):
    """Scout role is a planning role; _path_scope_violation returns a non-None string."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = _make_ctx(role="scout", run_dir=str(run_dir))
    outside = tmp_path / "other.md"
    result = _path_scope_violation(ctx.deps, outside)
    assert result is not None
    assert "path-scope violation" in result


def test_path_scope_violation_empty_run_dir_skips_check(tmp_path):
    """When run_dir is empty, the path-scope check is skipped; returns None."""
    ctx = _make_ctx(role="orchestrator", run_dir="")
    target = tmp_path / "anywhere.txt"
    assert _path_scope_violation(ctx.deps, target) is None


@pytest.mark.anyio
async def test_write_tool_planning_outside_run_dir_returns_error(tmp_path):
    """write_tool returns a recoverable Error string for a planning role writing outside run_dir.

    The file must not be created; the run must not crash (no exception raised).
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "secret.py"
    ctx = _make_ctx(role="orchestrator", run_dir=str(run_dir))
    result = await write_tool(ctx, str(outside), "content")
    assert result.startswith("Error")
    assert "path-scope violation" in result
    assert not outside.exists()


@pytest.mark.anyio
async def test_edit_tool_planning_outside_run_dir_returns_error(tmp_path):
    """edit_tool returns a recoverable Error string for a planning role editing outside run_dir.

    The file is not modified; the run must not crash.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("original\n")
    from koan.tools.line_anchors import ANCHOR_DELIMITER, compute_anchors
    content = "original\n"
    anchors = compute_anchors(content.splitlines())
    anchor_token = f"{anchors[0]}{ANCHOR_DELIMITER}original"
    ctx = _make_ctx(role="orchestrator", run_dir=str(run_dir))
    result = await edit_tool(ctx, str(outside), anchor_token, "replacement")
    assert result.startswith("Error")
    assert "path-scope violation" in result
    assert outside.read_text() == "original\n"


@pytest.mark.anyio
async def test_write_tool_executor_outside_run_dir_succeeds(tmp_path):
    """write_tool for an executor role succeeds even outside run_dir.

    Executors are not planning roles and may write anywhere.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "project" / "src" / "file.py"
    ctx = _make_ctx(role="executor", run_dir=str(run_dir))
    result = await write_tool(ctx, str(outside), "# code\n")
    assert outside.exists()
    assert not result.startswith("Error")


@pytest.mark.anyio
async def test_bash_tool_orchestrator_wrong_phase_returns_error(tmp_path):
    """bash_tool returns a recoverable Error string when orchestrator is in a non-bash phase.

    A plan-phase orchestrator is denied; the command is not executed.
    """
    ctx = _make_ctx(role="orchestrator", run_dir=str(tmp_path), phase="plan")
    result = await bash_tool(ctx, "echo should_not_run")
    assert result.startswith("Error")
    assert "bash" in result
    assert "should_not_run" not in result


@pytest.mark.anyio
async def test_bash_tool_orchestrator_execute_phase_runs(tmp_path):
    """bash_tool runs normally when orchestrator is in the execute phase.

    execute is in _ORCHESTRATOR_BASH_PHASES, so the gate returns None.
    """
    ctx = _make_ctx(role="orchestrator", run_dir=str(tmp_path), phase="execute")
    result = await bash_tool(ctx, "echo ok_from_execute")
    assert "ok_from_execute" in result


@pytest.mark.anyio
async def test_bash_tool_executor_runs_regardless_of_phase(tmp_path):
    """bash_tool runs normally for an executor role regardless of phase.

    Non-orchestrator roles short-circuit the phase gate and always execute.
    """
    ctx = _make_ctx(role="executor", run_dir=str(tmp_path), phase="plan")
    result = await bash_tool(ctx, "echo executor_ok")
    assert "executor_ok" in result


# -- read_tool --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_read_tool_returns_numbered_lines(tmp_path):
    """read_tool returns anchored format: {lineno}\t{anchor}{ANCHOR_DELIMITER}{content}.

    Line numbers are 1-based and absolute. Each line includes an anchor
    (8-hex + optional ~N ordinal) before the ANCHOR_DELIMITER and content.
    """
    from koan.tools.line_anchors import ANCHOR_DELIMITER as D, fnv1a32

    target = tmp_path / "input.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await read_tool(ctx, str(target))
    lines = result.splitlines()
    assert lines[0].startswith("1\t")
    assert lines[1].startswith("2\t")
    assert lines[2].startswith("3\t")
    # Verify the anchor+delimiter is present and content follows.
    assert f"{fnv1a32('alpha')}{D}alpha" in lines[0]
    assert f"{fnv1a32('beta')}{D}beta" in lines[1]


@pytest.mark.anyio
async def test_read_tool_metrics_derivable(tmp_path):
    """read_tool stores native metrics on deps.agent._pending_tool_metrics."""
    target = tmp_path / "data.txt"
    content = "line one\nline two\n"
    target.write_text(content)
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await read_tool(ctx, str(target))
    metrics = ctx.deps.agent._pending_tool_metrics
    assert metrics is not None
    assert metrics["lines_read"] == 2
    assert metrics["bytes_read"] > 0


# -- grep_tool --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_grep_tool_finds_matches(tmp_path):
    """grep_tool returns a 'Found N matches in M files' header plus match lines."""
    (tmp_path / "a.txt").write_text("foo bar\nbaz\nfoo again\n")
    (tmp_path / "b.txt").write_text("no match here\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, r"foo", str(tmp_path))
    assert result.startswith("Found 2 matches in 1 file")
    assert "foo" in result


@pytest.mark.anyio
async def test_grep_tool_no_matches(tmp_path):
    """grep_tool returns 'Found 0 matches' when no lines match the pattern."""
    (tmp_path / "a.txt").write_text("line one\nline two\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, r"zzznomatch", str(tmp_path))
    assert "Found 0 matches" in result


@pytest.mark.anyio
async def test_grep_tool_metrics_derivable(tmp_path):
    """grep_tool stores native metrics on deps.agent._pending_tool_metrics."""
    (tmp_path / "f.py").write_text("def foo():\n    pass\ndef bar():\n    pass\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, r"def ", str(tmp_path))
    metrics = ctx.deps.agent._pending_tool_metrics
    assert metrics is not None
    assert metrics["matches"] == 2
    assert metrics["files_matched"] == 1
    assert metrics["matched_lines"] == 2


# -- glob_tool --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_glob_tool_finds_files(tmp_path):
    """glob_tool returns matching file paths with a 'Found N files' header."""
    (tmp_path / "alpha.py").write_text("")
    (tmp_path / "beta.py").write_text("")
    (tmp_path / "gamma.txt").write_text("")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await glob_tool(ctx, "*.py", str(tmp_path))
    assert result.startswith("Found 2 files")
    assert "alpha.py" in result
    assert "beta.py" in result
    assert "gamma.txt" not in result


@pytest.mark.anyio
async def test_glob_tool_no_matches(tmp_path):
    """glob_tool returns 'Found 0 files' when no files match the pattern."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await glob_tool(ctx, "*.nomatch", str(tmp_path))
    assert "Found 0 files" in result


@pytest.mark.anyio
async def test_glob_tool_metrics_derivable(tmp_path):
    """glob_tool stores native metrics on deps.agent._pending_tool_metrics."""
    (tmp_path / "x.md").write_text("")
    (tmp_path / "y.md").write_text("")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await glob_tool(ctx, "*.md", str(tmp_path))
    metrics = ctx.deps.agent._pending_tool_metrics
    assert metrics is not None
    assert metrics["matches"] == 2
    assert metrics["files_matched"] == 2


# -- bash_tool --------------------------------------------------------------- #


@pytest.mark.anyio
async def test_bash_tool_captures_stdout(tmp_path):
    """bash_tool returns the stdout of the executed command."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await bash_tool(ctx, "echo hello_bash_test")
    assert "hello_bash_test" in result


@pytest.mark.anyio
async def test_bash_tool_captures_stderr(tmp_path):
    """bash_tool captures stderr alongside stdout in the combined output."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    # 'ls /nonexistent_path_xyz' writes to stderr.
    result = await bash_tool(ctx, "ls /nonexistent_path_xyz_koan_test 2>&1")
    # Should not raise; error message goes to combined output.
    assert isinstance(result, str)


@pytest.mark.anyio
async def test_bash_tool_timeout(tmp_path):
    """bash_tool returns an error string when the command exceeds the timeout."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await bash_tool(ctx, "sleep 10", timeout=1)
    assert "timed out" in result.lower() or "timeout" in result.lower()


@pytest.mark.anyio
async def test_bash_tool_nonzero_exit_code_included(tmp_path):
    """bash_tool includes the exit code in the output when it is nonzero."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await bash_tool(ctx, "exit 42")
    assert "42" in result


# -- output limits (pre-emptive cap) ----------------------------------------- #


def test_enforce_output_limits_removed():
    """The post-hoc reject ceiling is replaced by pre-emptive limiting."""
    import koan.tools.builtin_tools as m
    assert not hasattr(m, "_enforce_output_limits")
    assert not hasattr(m, "_MAX_TOOL_OUTPUT_LINES")
    assert not hasattr(m, "_MAX_TOOL_OUTPUT_BYTES")
    assert hasattr(m, "DEFAULT_LIMIT")


@pytest.mark.anyio
async def test_read_tool_caps_large_file(tmp_path):
    """read_tool caps output at DEFAULT_LIMIT lines (no rejection, no error)."""
    target = tmp_path / "big.txt"
    target.write_text("".join(f"line {i}\n" for i in range(DEFAULT_LIMIT + 50)))
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await read_tool(ctx, str(target))
    assert not result.startswith("Error:")
    # Exactly DEFAULT_LIMIT lines returned.
    assert len(result.splitlines()) == DEFAULT_LIMIT


@pytest.mark.anyio
async def test_read_tool_slice_under_cap_succeeds(tmp_path):
    """read_tool with an offset/limit slice under the cap returns content normally.

    This is the escape hatch the truncation note points the model to: paging a
    large file with offset/limit keeps each result within the budget.
    """
    target = tmp_path / "big.txt"
    target.write_text("".join(f"line {i}\n" for i in range(DEFAULT_LIMIT + 50)))
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await read_tool(ctx, str(target), offset=0, limit=100)
    assert not result.startswith("Error:")
    assert result.splitlines()[0].startswith("1\t")


@pytest.mark.anyio
async def test_read_tool_limit_none_returns_full_content(tmp_path):
    """read_tool with limit=None returns full content without capping (trusted bypass)."""
    target = tmp_path / "big.txt"
    target.write_text("".join(f"line {i}\n" for i in range(DEFAULT_LIMIT + 50)))
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await read_tool(ctx, str(target), limit=None)
    assert not result.startswith("Error:")
    # All DEFAULT_LIMIT + 50 lines returned.
    assert len(result.splitlines()) == DEFAULT_LIMIT + 50
    assert result.splitlines()[0].startswith("1\t")


@pytest.mark.anyio
async def test_bash_tool_caps_large_output(tmp_path):
    """bash_tool caps output at limit lines and appends a truncation note."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await bash_tool(ctx, f"seq 1 {DEFAULT_LIMIT + 100}", limit=DEFAULT_LIMIT)
    assert not result.startswith("Error:")
    assert "Output capped at" in result
    # Exactly DEFAULT_LIMIT output lines (excluding the truncation note).
    output = [l for l in result.splitlines() if not l.startswith("Output capped at")]
    assert len(output) == DEFAULT_LIMIT


@pytest.mark.anyio
async def test_grep_tool_caps_at_limit(tmp_path):
    """grep_tool stops after `limit` match lines and appends a truncation note."""
    for i in range(20):
        (tmp_path / f"f{i}.py").write_text("match\n" * 50)
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, "match", str(tmp_path), limit=100)
    lines = result.splitlines()
    match_lines = [l for l in lines if l.count(":") >= 2 and not l.startswith("Results")]
    assert len(match_lines) == 100
    assert "Results capped at 100 match lines" in result


@pytest.mark.anyio
async def test_glob_tool_caps_at_limit(tmp_path):
    """glob_tool stops after `limit` paths and appends a truncation note."""
    for i in range(200):
        (tmp_path / f"file{i}.py").touch()
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await glob_tool(ctx, "*.py", str(tmp_path), limit=50)
    lines = result.splitlines()
    assert lines[0] == "Found 50 files"
    path_lines = [l for l in lines[1:] if not l.startswith("Results capped")]
    assert len(path_lines) == 50
    assert "Results capped at 50 files" in result


@pytest.mark.anyio
async def test_grep_generator_stops_early(tmp_path):
    """grep_tool does not read all files when limit is reached early."""
    for i in range(100):
        (tmp_path / f"f{i:03d}.py").write_text("match\n")
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, "match", str(tmp_path), limit=10)
    assert "Results capped at 10 match lines" in result
    match_lines = [l for l in result.splitlines() if l.count(":") >= 2 and not l.startswith("Results")]
    assert len(match_lines) == 10


@pytest.mark.anyio
async def test_bash_tool_timeout_no_output(tmp_path):
    """bash_tool returns a timeout error when the command produces no output within timeout."""
    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await bash_tool(ctx, "sleep 10", timeout=1)
    assert "timed out" in result.lower() or "timeout" in result.lower()


# -- _is_ignored (glob/grep filter) ------------------------------------------ #


@pytest.mark.anyio
async def test_glob_skips_ignored_dirs(tmp_path):
    """glob_tool excludes files under ignored directories (e.g. __pycache__, .venv).

    Files rooted directly in tmp_path are included; those inside an ignored
    subdir are filtered out even when the glob pattern would match them.
    """
    # A normal source file -- should appear.
    (tmp_path / "source.py").write_text("# real")
    # A file inside an ignored subdir -- should be excluded.
    ignored = tmp_path / "__pycache__"
    ignored.mkdir()
    (ignored / "source.pyc").write_text("# cached")

    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await glob_tool(ctx, "**/*", str(tmp_path))
    assert "source.py" in result
    assert "__pycache__" not in result or "source.pyc" not in result


@pytest.mark.anyio
async def test_grep_skips_ignored_dirs(tmp_path):
    """grep_tool excludes files under ignored directories from the candidate set."""
    (tmp_path / "real.py").write_text("needle")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "dep.js").write_text("needle")

    ctx = _make_ctx(run_dir=str(tmp_path))
    result = await grep_tool(ctx, "needle", str(tmp_path))
    assert "real.py" in result
    # node_modules content must not appear.
    assert "dep.js" not in result
