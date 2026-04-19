# Tests for koan_memorize / koan_forget / koan_memory_status MCP tools.
#
# Exercises the raw handler functions (unwrapped from the FastMCP decorator),
# after wiring up a minimal AgentState + AppState + agent context var.

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from koan.state import AgentState, AppState
from koan.web import mcp_endpoint


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _unwrap(tool):
    """Extract the underlying async function from a FastMCP-decorated tool."""
    for attr in ("fn", "func", "_fn", "_func", "__wrapped__", "callback"):
        candidate = getattr(tool, attr, None)
        if callable(candidate):
            return candidate
    if callable(tool):
        return tool
    raise RuntimeError(f"Cannot unwrap FastMCP tool: {tool!r}")


memorize = _unwrap(mcp_endpoint.koan_memorize)
forget = _unwrap(mcp_endpoint.koan_forget)
memory_status = _unwrap(mcp_endpoint.koan_memory_status)


@pytest.fixture
def mem_env(tmp_path, monkeypatch):
    """Set up a minimal MCP environment with a tmp project directory.

    Returns a dict with the agent, app_state, and project_dir.
    """
    app_state = AppState()
    app_state.project_dir = str(tmp_path)
    app_state.phase = "curation"

    agent = AgentState(
        agent_id="test-agent-0001",
        role="orchestrator",
        subagent_dir=str(tmp_path / "sub"),
    )
    agent.run_dir = str(tmp_path)
    agent.step = 1
    app_state.agents[agent.agent_id] = agent

    # Wire module state + agent context var
    monkeypatch.setattr(mcp_endpoint, "_app_state", app_state)
    monkeypatch.setattr(mcp_endpoint, "_memory_store", None)
    token = mcp_endpoint._agent_ctx.set(agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "project_dir": tmp_path,
    }

    mcp_endpoint._agent_ctx.reset(token)
    mcp_endpoint._reset_memory_store()


# ---------------------------------------------------------------------------
# koan_memorize
# ---------------------------------------------------------------------------

class TestMemorize:
    @pytest.mark.anyio
    async def test_create_writes_to_flat_directory(self, mem_env):
        result_str = await memorize(
            type="decision",
            title="Use PostgreSQL",
            body="Documents the DB choice. Chose PostgreSQL 16.2 over SQLite.",
        )
        result = json.loads(result_str)
        assert result["op"] == "created"
        assert result["type"] == "decision"
        assert result["entry_id"] == 1
        assert result["created"] != ""
        assert result["modified"] != ""
        # File should exist in the flat .koan/memory/ directory
        project_dir = mem_env["project_dir"]
        target = project_dir / ".koan" / "memory" / "0001-use-postgresql.md"
        assert target.exists()

    @pytest.mark.anyio
    async def test_global_sequence_across_types(self, mem_env):
        r1 = json.loads(await memorize(type="decision", title="D1", body="Body."))
        r2 = json.loads(await memorize(type="lesson", title="L1", body="Body."))
        r3 = json.loads(await memorize(type="context", title="C1", body="Body."))
        assert r1["entry_id"] == 1
        assert r2["entry_id"] == 2
        assert r3["entry_id"] == 3
        project_dir = mem_env["project_dir"]
        mem = project_dir / ".koan" / "memory"
        assert (mem / "0001-d1.md").exists()
        assert (mem / "0002-l1.md").exists()
        assert (mem / "0003-c1.md").exists()

    @pytest.mark.anyio
    async def test_update_preserves_created(self, mem_env):
        create_result = json.loads(await memorize(
            type="decision",
            title="First",
            body="Body of first entry documenting a decision.",
        ))
        original_created = create_result["created"]

        update_result = json.loads(await memorize(
            type="decision",
            title="First Updated",
            body="Body of first entry documenting a decision, now revised.",
            entry_id=1,
        ))
        assert update_result["op"] == "updated"
        assert update_result["entry_id"] == 1
        assert update_result["created"] == original_created

    @pytest.mark.anyio
    async def test_invalid_type_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await memorize(type="opinion", title="X", body="Body.")
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"

    @pytest.mark.anyio
    async def test_update_nonexistent_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await memorize(
                type="decision",
                title="Nope",
                body="Body.",
                entry_id=999,
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "entry_not_found"

    @pytest.mark.anyio
    async def test_update_type_mismatch_raises(self, mem_env):
        await memorize(type="decision", title="D1", body="Body.")
        with pytest.raises(ToolError) as exc:
            await memorize(
                type="lesson",
                title="Wrong type",
                body="Body.",
                entry_id=1,
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "type_mismatch"


# ---------------------------------------------------------------------------
# koan_forget
# ---------------------------------------------------------------------------

class TestForget:
    @pytest.mark.anyio
    async def test_deletes_entry_by_id_without_type(self, mem_env):
        await memorize(type="decision", title="D1", body="Body.")

        result = json.loads(await forget(entry_id=1))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1
        assert result["type"] == "decision"

        project_dir = mem_env["project_dir"]
        target = project_dir / ".koan" / "memory" / "0001-d1.md"
        assert not target.exists()

    @pytest.mark.anyio
    async def test_deletes_with_matching_type(self, mem_env):
        await memorize(type="decision", title="D1", body="Body.")
        result = json.loads(await forget(entry_id=1, type="decision"))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1

    @pytest.mark.anyio
    async def test_type_mismatch_raises(self, mem_env):
        await memorize(type="decision", title="D1", body="Body.")
        with pytest.raises(ToolError) as exc:
            await forget(entry_id=1, type="lesson")
        body = json.loads(str(exc.value))
        assert body["error"] == "type_mismatch"

    @pytest.mark.anyio
    async def test_nonexistent_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await forget(entry_id=42)
        body = json.loads(str(exc.value))
        assert body["error"] == "entry_not_found"

    @pytest.mark.anyio
    async def test_invalid_type_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await forget(entry_id=1, type="wrong")
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"


# ---------------------------------------------------------------------------
# koan_memory_status
# ---------------------------------------------------------------------------

class TestMemoryStatus:
    @pytest.mark.anyio
    async def test_returns_summary_and_flat_entries(self, mem_env):
        await memorize(type="decision", title="D1", body="Body of decision one.")
        await memorize(type="lesson", title="L1", body="Body of lesson one.")

        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked summary body"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            raw = await memory_status()
        result = json.loads(raw)

        assert "summary" in result
        assert "entries" in result
        assert "regenerated" in result
        assert "types" not in result  # old shape must be gone
        assert result["regenerated"] is True

        titles = [e["title"] for e in result["entries"]]
        types = [e["type"] for e in result["entries"]]
        assert titles == ["D1", "L1"]
        assert types == ["decision", "lesson"]
        # Each entry exposes id + timestamps
        assert result["entries"][0]["entry_id"] == 1
        assert result["entries"][0]["created"] != ""
        assert result["entries"][0]["modified"] != ""

    @pytest.mark.anyio
    async def test_type_filter(self, mem_env):
        await memorize(type="decision", title="D1", body="Decision body.")
        await memorize(type="lesson", title="L1", body="Lesson body.")

        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            raw = await memory_status(type="decision")
        result = json.loads(raw)
        titles = [e["title"] for e in result["entries"]]
        assert titles == ["D1"]
        # Summary is project-wide regardless of filter
        assert "summary" in result

    @pytest.mark.anyio
    async def test_staleness_detection(self, mem_env):
        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked"

        # First call: no entries, no summary -> not stale, not regenerated
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            first = json.loads(await memory_status())
        assert first["regenerated"] is False
        assert first["entries"] == []

        # Add an entry -> stale -> regenerate
        await memorize(type="decision", title="D1", body="First.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            second = json.loads(await memory_status())
        assert second["regenerated"] is True

        # Third call without changes -> summary is fresh -> no regeneration
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            third = json.loads(await memory_status())
        assert third["regenerated"] is False

        # Give filesystem mtime a chance to advance past the summary mtime
        time.sleep(0.02)

        # Add another entry -> stale -> regenerate
        await memorize(type="decision", title="D2", body="Second.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            fourth = json.loads(await memory_status())
        assert fourth["regenerated"] is True

    @pytest.mark.anyio
    async def test_empty_memory_no_regeneration(self, mem_env):
        # Empty memory should return an empty entries list without calling
        # the LLM, so no patch is needed.
        raw = await memory_status()
        result = json.loads(raw)
        assert result["entries"] == []
        assert result["regenerated"] is False
        assert result["summary"] == ""
