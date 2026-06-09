# Unit tests for koan.tools.context_files.
#
# Tests context-file discovery, directory walk, message formatting,
# and history-processor injection / dedup semantics. All tests use
# tmp_path; no network calls are made.

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from koan.tools.context_files import (
    discover_context_file,
    format_context_message,
    make_context_history_processor,
    walk_for_context_files,
)


# -- discover_context_file --------------------------------------------------- #


def test_discover_agents_md_found(tmp_path):
    """discover_context_file returns the path of AGENTS.md when present."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Agents")
    result = discover_context_file(str(tmp_path))
    assert result is not None
    assert Path(result).name == "AGENTS.md"


def test_discover_claude_md_fallback(tmp_path):
    """discover_context_file falls back to CLAUDE.md when AGENTS.md is absent."""
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# Claude")
    result = discover_context_file(str(tmp_path))
    assert result is not None
    assert Path(result).name == "CLAUDE.md"


def test_discover_agents_md_over_claude_md(tmp_path):
    """discover_context_file prefers AGENTS.md over CLAUDE.md."""
    (tmp_path / "AGENTS.md").write_text("# Agents")
    (tmp_path / "CLAUDE.md").write_text("# Claude")
    result = discover_context_file(str(tmp_path))
    assert result is not None
    assert Path(result).name == "AGENTS.md"


def test_discover_none_when_absent(tmp_path):
    """discover_context_file returns None when neither AGENTS.md nor CLAUDE.md exist."""
    result = discover_context_file(str(tmp_path))
    assert result is None


# -- walk_for_context_files -------------------------------------------------- #


def test_walk_returns_subtree_files_bottom_up(tmp_path):
    """walk_for_context_files returns context files from deepest to shallowest.

    Given a tree:
        tmp_path/AGENTS.md
        tmp_path/sub/AGENTS.md
        tmp_path/sub/deep/file.txt

    A touch on file.txt should discover sub/AGENTS.md (deepest first) then
    tmp_path/AGENTS.md.
    """
    (tmp_path / "AGENTS.md").write_text("root")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("sub")
    deep = sub / "deep"
    deep.mkdir()
    (deep / "file.txt").write_text("content")

    results = walk_for_context_files(
        str(deep / "file.txt"),
        str(tmp_path),
        injected=set(),
    )
    paths = [Path(p).name for p in results]
    assert paths.count("AGENTS.md") == 2
    # sub/AGENTS.md should appear before root AGENTS.md (bottom-up).
    sub_idx = next(i for i, p in enumerate(results) if "sub" in p and "deep" not in p)
    root_idx = next(i for i, p in enumerate(results) if str(tmp_path / "AGENTS.md") == p)
    assert sub_idx < root_idx


def test_walk_stops_at_injected_ancestor(tmp_path):
    """walk_for_context_files stops ascending when it hits an already-injected ancestor.

    If sub/AGENTS.md is already injected, the walk should not return it or any
    file above it (root AGENTS.md), since the ancestor is already covered.
    """
    (tmp_path / "AGENTS.md").write_text("root")
    sub = tmp_path / "sub"
    sub.mkdir()
    sub_agents = sub / "AGENTS.md"
    sub_agents.write_text("sub")
    deep = sub / "deep"
    deep.mkdir()
    touched = deep / "file.txt"
    touched.write_text("x")

    already_injected = {str(sub_agents.resolve())}
    results = walk_for_context_files(str(touched), str(tmp_path), injected=already_injected)
    # Neither sub/AGENTS.md (injected) nor root AGENTS.md (above injected) should appear.
    assert len(results) == 0


def test_walk_never_above_project_root(tmp_path):
    """walk_for_context_files never returns files above project_root."""
    sub = tmp_path / "project"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("inside project")
    # Put an AGENTS.md ABOVE the project root (i.e. in tmp_path itself).
    (tmp_path / "AGENTS.md").write_text("outside project")

    touched = sub / "file.txt"
    touched.write_text("content")

    # project root is sub, so tmp_path/AGENTS.md must not be returned.
    results = walk_for_context_files(str(touched), str(sub), injected=set())
    result_paths = [Path(p) for p in results]
    for p in result_paths:
        # All returned paths must be inside (or equal to) the project root.
        p.relative_to(sub)  # raises ValueError if not inside sub


def test_walk_returns_empty_for_empty_project_root(tmp_path):
    """walk_for_context_files returns [] when project_root is empty."""
    touched = tmp_path / "file.txt"
    touched.write_text("content")
    results = walk_for_context_files(str(touched), "", injected=set())
    assert results == []


# -- format_context_message -------------------------------------------------- #


def test_format_context_message_envelope():
    """format_context_message wraps content in <project_instructions> inside <system-reminder>."""
    msg = format_context_message("/project/AGENTS.md", "## Instructions\nDo this.")
    assert "<system-reminder>" in msg
    assert "<project_instructions" in msg
    assert "/project/AGENTS.md" in msg
    assert "## Instructions" in msg
    assert "</project_instructions>" in msg
    assert "</system-reminder>" in msg


# -- make_context_history_processor ------------------------------------------ #


def _make_deps(tmp_path: Path) -> SimpleNamespace:
    """Build a minimal ToolDeps-like namespace for processor tests."""
    agent = SimpleNamespace(
        injected_context_files=set(),
        pending_context_files=[],
    )
    return SimpleNamespace(agent=agent)


def _make_run_ctx(messages: list) -> SimpleNamespace:
    """Build a minimal RunContext-like namespace for processor tests."""
    return SimpleNamespace(messages=messages)


@pytest.mark.anyio
async def test_processor_injects_pending_file(tmp_path):
    """History processor injects a pending context file as a user message.

    After the processor runs, the file should appear as a ModelRequest in
    the returned message list and be added to injected_context_files.
    """
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Project agents instructions")

    deps = _make_deps(tmp_path)
    deps.agent.pending_context_files.append(str(agents_md.resolve()))

    processor = make_context_history_processor(deps)
    existing_messages: list = []
    ctx = _make_run_ctx(existing_messages)

    result = await processor(ctx, [])
    assert len(result) == 1
    # The message should contain the file content.
    from pydantic_ai.messages import ModelRequest
    assert isinstance(result[0], ModelRequest)
    part = result[0].parts[0]
    assert "Project agents instructions" in part.content
    assert "<project_instructions" in part.content

    # File should be recorded in injected_context_files.
    assert str(agents_md.resolve()) in deps.agent.injected_context_files


@pytest.mark.anyio
async def test_processor_deduplicates_files(tmp_path):
    """History processor skips files already in injected_context_files."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Already seen")
    path_str = str(agents_md.resolve())

    deps = _make_deps(tmp_path)
    deps.agent.pending_context_files.append(path_str)
    deps.agent.injected_context_files.add(path_str)  # already injected

    processor = make_context_history_processor(deps)
    ctx = _make_run_ctx([])
    result = await processor(ctx, [])
    # Already injected -- should be a no-op.
    assert len(result) == 0


@pytest.mark.anyio
async def test_processor_persists_messages_to_live_history(tmp_path):
    """Processor appends injected messages to ctx.messages (live history)."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Instructions")

    deps = _make_deps(tmp_path)
    deps.agent.pending_context_files.append(str(agents_md.resolve()))

    processor = make_context_history_processor(deps)
    live_history: list = []
    ctx = _make_run_ctx(live_history)

    await processor(ctx, [])

    # The live history (ctx.messages) must have the injected message.
    assert len(live_history) == 1
    assert "<project_instructions" in live_history[0].parts[0].content


@pytest.mark.anyio
async def test_processor_project_dir_file_appears_first(tmp_path):
    """Project-directory context file injected at loop start appears first in messages.

    Simulates: project root has AGENTS.md, a subdirectory also has AGENTS.md.
    The project-dir file is seeded into pending_context_files first (by pydantic_ai.py),
    the subdirectory file is queued second. Processor should inject them in order.
    """
    root_agents = tmp_path / "AGENTS.md"
    root_agents.write_text("# Root instructions")
    sub = tmp_path / "sub"
    sub.mkdir()
    sub_agents = sub / "AGENTS.md"
    sub_agents.write_text("# Sub instructions")

    deps = _make_deps(tmp_path)
    # Project dir file seeded first (as pydantic_ai.py does at loop start).
    deps.agent.pending_context_files.append(str(root_agents.resolve()))
    # Sub-dir file queued second (as path-recording would do).
    deps.agent.pending_context_files.append(str(sub_agents.resolve()))

    processor = make_context_history_processor(deps)
    ctx = _make_run_ctx([])
    result = await processor(ctx, [])

    assert len(result) == 2
    # Root file must come first.
    assert "Root instructions" in result[0].parts[0].content
    assert "Sub instructions" in result[1].parts[0].content


@pytest.mark.anyio
async def test_processor_skips_unreadable_file(tmp_path):
    """Processor silently skips context files that cannot be read (no exception)."""
    deps = _make_deps(tmp_path)
    deps.agent.pending_context_files.append(str(tmp_path / "nonexistent_AGENTS.md"))

    processor = make_context_history_processor(deps)
    ctx = _make_run_ctx([])
    # Should not raise.
    result = await processor(ctx, [])
    assert len(result) == 0
