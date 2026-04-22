# Tests for koan_memorize / koan_forget / koan_memory_status MCP tools.
#
# Invokes handler closures directly via build_mcp_server() + _FakeContext,
# bypassing the HTTP dispatch layer. This replaces the old _unwrap() approach
# that accessed module-level decorated functions no longer exported.

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from koan.state import AgentState, AppState


# ---------------------------------------------------------------------------
# Shared fake context
# ---------------------------------------------------------------------------

class _FakeContext:
    """Minimal fastmcp Context substitute for calling handler closures in tests."""
    def __init__(self, agent):
        self._agent = agent

    async def get_state(self, key):
        if key == "agent":
            return self._agent
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_env(tmp_path):
    """Set up a minimal MCP environment with a tmp project directory.

    Builds the server via build_mcp_server so tests call real handler closures.
    Exposes handlers, ctx, agent, app_state, and project_dir.
    """
    from koan.web.mcp_endpoint import build_mcp_server

    app_state = AppState()
    app_state.run.project_dir = str(tmp_path)
    # curation is a valid phase for all memory tools per permissions.py
    app_state.run.phase = "curation"

    agent = AgentState(
        agent_id="test-agent-0001",
        role="orchestrator",
        subagent_dir=str(tmp_path / "sub"),
    )
    agent.run_dir = str(tmp_path)
    agent.step = 1
    app_state.agents[agent.agent_id] = agent
    app_state.init_memory_services()

    _, handlers = build_mcp_server(app_state)
    ctx = _FakeContext(agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "project_dir": tmp_path,
        "ctx": ctx,
        "handlers": handlers,
    }


# ---------------------------------------------------------------------------
# koan_memorize
# ---------------------------------------------------------------------------

class TestMemorize:
    @pytest.mark.anyio
    async def test_create_writes_to_flat_directory(self, mem_env):
        result_str = await mem_env["handlers"].koan_memorize(
            mem_env["ctx"],
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
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        r1 = json.loads(await h.koan_memorize(ctx, type="decision", title="D1", body="Body."))
        r2 = json.loads(await h.koan_memorize(ctx, type="lesson", title="L1", body="Body."))
        r3 = json.loads(await h.koan_memorize(ctx, type="context", title="C1", body="Body."))
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
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        create_result = json.loads(await h.koan_memorize(
            ctx,
            type="decision",
            title="First",
            body="Body of first entry documenting a decision.",
        ))
        original_created = create_result["created"]

        update_result = json.loads(await h.koan_memorize(
            ctx,
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
            await mem_env["handlers"].koan_memorize(
                mem_env["ctx"], type="opinion", title="X", body="Body."
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"

    @pytest.mark.anyio
    async def test_update_nonexistent_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_memorize(
                mem_env["ctx"],
                type="decision",
                title="Nope",
                body="Body.",
                entry_id=999,
            )
        body = json.loads(str(exc.value))
        assert body["error"] == "entry_not_found"

    @pytest.mark.anyio
    async def test_update_type_mismatch_raises(self, mem_env):
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Body.")
        with pytest.raises(ToolError) as exc:
            await h.koan_memorize(
                ctx,
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
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Body.")

        result = json.loads(await h.koan_forget(ctx, entry_id=1))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1
        assert result["type"] == "decision"

        project_dir = mem_env["project_dir"]
        target = project_dir / ".koan" / "memory" / "0001-d1.md"
        assert not target.exists()

    @pytest.mark.anyio
    async def test_deletes_with_matching_type(self, mem_env):
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Body.")
        result = json.loads(await h.koan_forget(ctx, entry_id=1, type="decision"))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1

    @pytest.mark.anyio
    async def test_type_mismatch_raises(self, mem_env):
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Body.")
        with pytest.raises(ToolError) as exc:
            await h.koan_forget(ctx, entry_id=1, type="lesson")
        body = json.loads(str(exc.value))
        assert body["error"] == "type_mismatch"

    @pytest.mark.anyio
    async def test_nonexistent_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_forget(mem_env["ctx"], entry_id=42)
        body = json.loads(str(exc.value))
        assert body["error"] == "entry_not_found"

    @pytest.mark.anyio
    async def test_invalid_type_raises(self, mem_env):
        with pytest.raises(ToolError) as exc:
            await mem_env["handlers"].koan_forget(mem_env["ctx"], entry_id=1, type="wrong")
        body = json.loads(str(exc.value))
        assert body["error"] == "invalid_type"


# ---------------------------------------------------------------------------
# koan_memory_status
# ---------------------------------------------------------------------------

class TestMemoryStatus:
    @pytest.mark.anyio
    async def test_returns_summary_and_flat_entries(self, mem_env):
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Body of decision one.")
        await h.koan_memorize(ctx, type="lesson", title="L1", body="Body of lesson one.")

        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked summary body"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            raw = await h.koan_memory_status(ctx)
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
        h, ctx = mem_env["handlers"], mem_env["ctx"]
        await h.koan_memorize(ctx, type="decision", title="D1", body="Decision body.")
        await h.koan_memorize(ctx, type="lesson", title="L1", body="Lesson body.")

        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            raw = await h.koan_memory_status(ctx, type="decision")
        result = json.loads(raw)
        titles = [e["title"] for e in result["entries"]]
        assert titles == ["D1"]
        # Summary is project-wide regardless of filter
        assert "summary" in result

    @pytest.mark.anyio
    async def test_staleness_detection(self, mem_env):
        h, ctx = mem_env["handlers"], mem_env["ctx"]

        async def fake_generate(prompt, system="", max_tokens=1024):
            return "mocked"

        # First call: no entries, no summary -> not stale, not regenerated
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            first = json.loads(await h.koan_memory_status(ctx))
        assert first["regenerated"] is False
        assert first["entries"] == []

        # Add an entry -> stale -> regenerate
        await h.koan_memorize(ctx, type="decision", title="D1", body="First.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            second = json.loads(await h.koan_memory_status(ctx))
        assert second["regenerated"] is True

        # Third call without changes -> summary is fresh -> no regeneration
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            third = json.loads(await h.koan_memory_status(ctx))
        assert third["regenerated"] is False

        # Give filesystem mtime a chance to advance past the summary mtime
        time.sleep(0.02)

        # Add another entry -> stale -> regenerate
        await h.koan_memorize(ctx, type="decision", title="D2", body="Second.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            fourth = json.loads(await h.koan_memory_status(ctx))
        assert fourth["regenerated"] is True

    @pytest.mark.anyio
    async def test_empty_memory_no_regeneration(self, mem_env):
        # Empty memory should return an empty entries list without calling
        # the LLM, so no patch is needed.
        raw = await mem_env["handlers"].koan_memory_status(mem_env["ctx"])
        result = json.loads(raw)
        assert result["entries"] == []
        assert result["regenerated"] is False
        assert result["summary"] == ""
