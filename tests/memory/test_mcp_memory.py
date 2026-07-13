# Tests for memorize_core / forget_core / memory_status_core.
#
# Calls the in-process cores directly via ToolDeps, bypassing the deleted
# HTTP MCP transport. Cores return a JSON string; errors are raised as
# ValueError / EntryNotFoundError / TypeMismatchError (not ToolError).

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from koan.memory.bindings import MemoryModels
from koan.state import AgentState, AppState
from koan.types import ModelSpec
from koan.models.offering import resolve_offering


def _json(result: str) -> dict:
    """JSON-decode a core result string."""
    return json.loads(result)




def _fake_embed() -> ModelSpec:
    return ModelSpec(offering=resolve_offering("voyage", "voyage-4-large"), thinking="disabled",
                     connection_id="v", embedding_dim=1024, api_key="k")


def _fake_models() -> MemoryModels:
    # Only the embedding binding remains; the dedicated LLM fields were removed.
    return MemoryModels(embedding=_fake_embed())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_env(tmp_path):
    """Set up a minimal in-process environment with a tmp project directory.

    Builds ToolDeps directly so tests call core functions without fastmcp.
    Exposes deps, agent, app_state, and project_dir.
    """
    from koan.tools.koan_tools import ToolDeps

    app_state = AppState()
    app_state.run.project_dir = str(tmp_path)
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
    # Provide fake memory models so memory_status_core can attempt summary regeneration.
    app_state.run.memory_models = _fake_models()
    # memory_status_core resolves the cheap model from frozen_models["cheap"];
    # without it, summary regeneration is skipped (model=None guard in ops.status).
    app_state.run.frozen_models = {"cheap": _fake_embed()}

    deps = ToolDeps(app_state=app_state, agent=agent)

    yield {
        "agent": agent,
        "app_state": app_state,
        "project_dir": tmp_path,
        "deps": deps,
    }


# ---------------------------------------------------------------------------
# memorize_core
# ---------------------------------------------------------------------------

class TestMemorize:
    @pytest.mark.anyio
    async def test_create_writes_to_flat_directory(self, mem_env):
        from koan.tools.koan_tools import memorize_core
        result = _json(await memorize_core(
            mem_env["deps"],
            type="decision",
            title="Use PostgreSQL",
            body="Documents the DB choice. Chose PostgreSQL 16.2 over SQLite.",
        ))
        assert result["op"] == "created"
        assert result["type"] == "decision"
        assert result["entry_id"] == 1
        assert result["created"] != ""
        assert result["modified"] != ""
        project_dir = mem_env["project_dir"]
        target = project_dir / ".koan" / "memory" / "0001-use-postgresql.md"
        assert target.exists()

    @pytest.mark.anyio
    async def test_global_sequence_across_types(self, mem_env):
        from koan.tools.koan_tools import memorize_core
        deps = mem_env["deps"]
        r1 = _json(await memorize_core(deps, type="decision", title="D1", body="Body."))
        r2 = _json(await memorize_core(deps, type="lesson", title="L1", body="Body."))
        r3 = _json(await memorize_core(deps, type="context", title="C1", body="Body."))
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
        from koan.tools.koan_tools import memorize_core
        deps = mem_env["deps"]
        create_result = _json(await memorize_core(
            deps,
            type="decision",
            title="First",
            body="Body of first entry documenting a decision.",
        ))
        original_created = create_result["created"]

        update_result = _json(await memorize_core(
            deps,
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
        from koan.tools.koan_tools import memorize_core
        with pytest.raises(ValueError) as exc:
            await memorize_core(
                mem_env["deps"], type="opinion", title="X", body="Body."
            )
        assert "invalid" in str(exc.value).lower() or "opinion" in str(exc.value)

    @pytest.mark.anyio
    async def test_update_nonexistent_raises(self, mem_env):
        from koan.memory.ops import EntryNotFoundError
        from koan.tools.koan_tools import memorize_core
        with pytest.raises(EntryNotFoundError):
            await memorize_core(
                mem_env["deps"],
                type="decision",
                title="Nope",
                body="Body.",
                entry_id=999,
            )

    @pytest.mark.anyio
    async def test_update_type_mismatch_raises(self, mem_env):
        from koan.memory.ops import TypeMismatchError
        from koan.tools.koan_tools import memorize_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Body.")
        with pytest.raises(TypeMismatchError):
            await memorize_core(
                deps,
                type="lesson",
                title="Wrong type",
                body="Body.",
                entry_id=1,
            )


# ---------------------------------------------------------------------------
# forget_core
# ---------------------------------------------------------------------------

class TestForget:
    @pytest.mark.anyio
    async def test_deletes_entry_by_id_without_type(self, mem_env):
        from koan.tools.koan_tools import forget_core, memorize_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Body.")

        result = _json(await forget_core(deps, entry_id=1))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1
        assert result["type"] == "decision"

        project_dir = mem_env["project_dir"]
        target = project_dir / ".koan" / "memory" / "0001-d1.md"
        assert not target.exists()

    @pytest.mark.anyio
    async def test_deletes_with_matching_type(self, mem_env):
        from koan.tools.koan_tools import forget_core, memorize_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Body.")
        result = _json(await forget_core(deps, entry_id=1, type="decision"))
        assert result["op"] == "forgotten"
        assert result["entry_id"] == 1

    @pytest.mark.anyio
    async def test_type_mismatch_raises(self, mem_env):
        from koan.memory.ops import TypeMismatchError
        from koan.tools.koan_tools import forget_core, memorize_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Body.")
        with pytest.raises(TypeMismatchError):
            await forget_core(deps, entry_id=1, type="lesson")

    @pytest.mark.anyio
    async def test_nonexistent_raises(self, mem_env):
        from koan.memory.ops import EntryNotFoundError
        from koan.tools.koan_tools import forget_core
        with pytest.raises(EntryNotFoundError):
            await forget_core(mem_env["deps"], entry_id=42)

    @pytest.mark.anyio
    async def test_invalid_type_raises(self, mem_env):
        from koan.tools.koan_tools import forget_core
        with pytest.raises(ValueError):
            await forget_core(mem_env["deps"], entry_id=1, type="wrong")


# ---------------------------------------------------------------------------
# memory_status_core
# ---------------------------------------------------------------------------

class TestMemoryStatus:
    @pytest.mark.anyio
    async def test_returns_summary_and_flat_entries(self, mem_env):
        from koan.tools.koan_tools import memorize_core, memory_status_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Body of decision one.")
        await memorize_core(deps, type="lesson", title="L1", body="Body of lesson one.")

        async def fake_generate(prompt, model=None, system="", max_tokens=1024):
            return "mocked summary body"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            result = _json(await memory_status_core(deps))

        assert "summary" in result
        assert "entries" in result
        assert "regenerated" in result
        assert "types" not in result  # old shape must be gone
        assert result["regenerated"] is True

        titles = [e["title"] for e in result["entries"]]
        types = [e["type"] for e in result["entries"]]
        assert titles == ["D1", "L1"]
        assert types == ["decision", "lesson"]
        assert result["entries"][0]["entry_id"] == 1
        assert result["entries"][0]["created"] != ""
        assert result["entries"][0]["modified"] != ""

    @pytest.mark.anyio
    async def test_type_filter(self, mem_env):
        from koan.tools.koan_tools import memorize_core, memory_status_core
        deps = mem_env["deps"]
        await memorize_core(deps, type="decision", title="D1", body="Decision body.")
        await memorize_core(deps, type="lesson", title="L1", body="Lesson body.")

        async def fake_generate(prompt, model=None, system="", max_tokens=1024):
            return "mocked"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            result = _json(await memory_status_core(deps, type="decision"))
        titles = [e["title"] for e in result["entries"]]
        assert titles == ["D1"]
        assert "summary" in result

    @pytest.mark.anyio
    async def test_staleness_detection(self, mem_env):
        from koan.tools.koan_tools import memorize_core, memory_status_core
        deps = mem_env["deps"]

        async def fake_generate(prompt, model=None, system="", max_tokens=1024):
            return "mocked"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            first = _json(await memory_status_core(deps))
        assert first["regenerated"] is False
        assert first["entries"] == []

        await memorize_core(deps, type="decision", title="D1", body="First.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            second = _json(await memory_status_core(deps))
        assert second["regenerated"] is True

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            third = _json(await memory_status_core(deps))
        assert third["regenerated"] is False

        time.sleep(0.02)

        await memorize_core(deps, type="decision", title="D2", body="Second.")
        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            fourth = _json(await memory_status_core(deps))
        assert fourth["regenerated"] is True

    @pytest.mark.anyio
    async def test_empty_memory_no_regeneration(self, mem_env):
        from koan.tools.koan_tools import memory_status_core
        result = _json(await memory_status_core(mem_env["deps"]))
        assert result["entries"] == []
        assert result["regenerated"] is False
        assert result["summary"] == ""
