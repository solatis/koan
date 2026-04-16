# Tests for koan.memory.summarize
# Unit tests mock the LLM; integration tests require GEMINI_API_KEY.

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from koan.memory.store import MemoryStore
from koan.memory.summarize import (
    _render_entries_for_prompt,
    generate_summary,
    regenerate_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populated_store(tmp_path):
    """Create a store with sample entries across types."""
    store = MemoryStore(tmp_path)
    store.init()
    store.add_entry(
        "decision", "PostgreSQL for Auth",
        "Documents the choice of primary data store. "
        "On 2026-04-10, user chose PostgreSQL 16.2 over SQLite.",
    )
    store.add_entry(
        "decision", "No Unit Tests",
        "Documents the testing policy for TrapperKeeper. "
        "On 2026-04-08, user established integration-only testing.",
    )
    store.add_entry(
        "context", "Team and Infrastructure",
        "Captures team and infra context. "
        "On 2026-04-01, team documented deployment on a single Hetzner VM.",
    )
    store.add_entry(
        "lesson", "Executor Generated Unit Tests",
        "Records an executor policy violation. "
        "On 2026-04-09, executor generated unit tests despite policy.",
    )
    store.add_entry(
        "procedure", "Check Testing Policy First",
        "Rule for any code-generation task. "
        "On 2026-04-09, team adopted policy: always read test policy first.",
    )
    return store


# ---------------------------------------------------------------------------
# Unit tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestRenderEntries:
    def test_includes_title_and_body(self, tmp_path):
        store = _populated_store(tmp_path)
        text = _render_entries_for_prompt(store.list_entries())
        assert "PostgreSQL for Auth" in text
        assert "integration-only testing" in text
        assert "Hetzner VM" in text


class TestGenerateSummary:
    @pytest.mark.anyio
    async def test_reads_entries_directly(self, tmp_path):
        store = _populated_store(tmp_path)
        captured = {}

        async def fake_generate(prompt, system="", max_tokens=1024):
            captured["prompt"] = prompt
            captured["system"] = system
            return "# TrapperKeeper\n\nProject summary here."

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            summary = await generate_summary(store, project_name="TrapperKeeper")

        prompt = captured["prompt"]
        # All entry titles should appear in the prompt (read directly, not indirectly via indexes)
        assert "PostgreSQL for Auth" in prompt
        assert "No Unit Tests" in prompt
        assert "Team and Infrastructure" in prompt
        assert "Executor Generated Unit Tests" in prompt
        assert "Check Testing Policy First" in prompt
        # Project name surfaces in prompt
        assert "TrapperKeeper" in prompt
        # System prompt should be the summary system prompt
        assert "briefing document" in captured["system"]
        # Result written to disk
        assert summary == "# TrapperKeeper\n\nProject summary here."
        assert store.get_summary() is not None
        assert "TrapperKeeper" in store.get_summary()

    @pytest.mark.anyio
    async def test_no_entries_produces_empty_summary(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.init()

        summary = await generate_summary(store)
        assert "No memory entries" in summary
        # Written to disk too
        assert store.get_summary() is not None

    @pytest.mark.anyio
    async def test_llm_failure_propagates(self, tmp_path):
        store = _populated_store(tmp_path)

        async def failing_generate(prompt, system="", max_tokens=1024):
            raise RuntimeError("API error")

        with patch("koan.memory.summarize.generate", side_effect=failing_generate):
            with pytest.raises(RuntimeError, match="API error"):
                await generate_summary(store)

        # summary.md must not be written on failure
        assert not (store._memory_dir / "summary.md").exists()

    @pytest.mark.anyio
    async def test_forgotten_entry_not_in_prompt(self, tmp_path):
        store = _populated_store(tmp_path)
        # Forget one entry
        to_forget = store.list_entries(type="decision")[0]
        store.forget_entry(to_forget)

        captured = {}

        async def fake_generate(prompt, system="", max_tokens=1024):
            captured["prompt"] = prompt
            return "summary"

        with patch("koan.memory.summarize.generate", side_effect=fake_generate):
            await generate_summary(store)

        assert "PostgreSQL for Auth" not in captured["prompt"]


class TestRegenerateSummary:
    @pytest.mark.anyio
    async def test_delegates_to_generate_summary(self, tmp_path):
        store = _populated_store(tmp_path)
        called = {}

        async def fake_generate_summary(s, project_name=""):
            called["store"] = s
            called["name"] = project_name
            return "stub"

        with patch(
            "koan.memory.summarize.generate_summary",
            side_effect=fake_generate_summary,
        ):
            await regenerate_summary(store, project_name="Foo")

        assert called["store"] is store
        assert called["name"] == "Foo"


class TestStoreRegenerateSummary:
    @pytest.mark.anyio
    async def test_delegates_to_module(self, tmp_path):
        store = _populated_store(tmp_path)
        called = {}

        async def mock_regen(s, project_name=""):
            called["store"] = s
            called["name"] = project_name

        with patch("koan.memory.summarize.regenerate_summary", mock_regen):
            await store.regenerate_summary(project_name="Foo")

        assert called["store"] is store
        assert called["name"] == "Foo"


# ---------------------------------------------------------------------------
# Integration tests (require API key)
# ---------------------------------------------------------------------------

_SKIP_NO_KEY = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

# gemini-3-flash-lite is the spec default but may not be available yet;
# fall back to the latest available lite model for integration tests.
_INTEGRATION_MODEL = os.environ.get("KOAN_LLM_MODEL") or "gemini-2.5-flash-lite"


@_SKIP_NO_KEY
class TestIntegrationSummary:
    @pytest.mark.anyio
    async def test_produces_coherent_overview(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KOAN_LLM_MODEL", _INTEGRATION_MODEL)
        store = _populated_store(tmp_path)
        summary = await generate_summary(store, project_name="TrapperKeeper")
        assert len(summary) > 50
        assert store.get_summary() is not None
