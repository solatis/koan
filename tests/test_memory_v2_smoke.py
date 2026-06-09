# Smoke tests confirming the memory module runs under pydantic-ai v2.0.0b6.
# Live Gemini tests are gated on credentials; they skip cleanly when absent.
# After the credential-store migration, tests use the real_credential_store
# fixture to initialize the active store from real env vars.

from __future__ import annotations

import os

import pytest

# Module-level skip marker still checks env vars directly -- this runs before
# any fixture, so it tells pytest whether to schedule the live tests at all.
_HAS_GEMINI_CREDS = bool(
    os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
)

_SKIP_NO_CREDS = pytest.mark.skipif(
    not _HAS_GEMINI_CREDS,
    reason="no Gemini credentials (GOOGLE_API_KEY or GEMINI_API_KEY not set)",
)


class TestMemoryLlmV2Smoke:
    @pytest.mark.anyio
    @_SKIP_NO_CREDS
    async def test_generate_returns_nonempty_string(self, real_credential_store):
        """koan.memory.llm.generate returns a non-empty string under v2.0.0b6."""
        from koan.memory.llm import generate

        result = await generate("Reply with the single word: ok")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.anyio
    @_SKIP_NO_CREDS
    async def test_generate_with_system_prompt(self, real_credential_store):
        """koan.memory.llm.generate handles a system prompt under v2.0.0b6."""
        from koan.memory.llm import generate

        result = await generate(
            "What is 2+2?",
            system="You are a concise calculator. Reply with only the number.",
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestReflectAgentV2Import:
    def test_reflect_imports_cleanly(self):
        """koan.memory.retrieval.reflect imports without error under v2.0.0b6."""
        import koan.memory.retrieval.reflect as r
        assert hasattr(r, "run_reflect_agent")
        assert hasattr(r, "ReflectResult")
        assert hasattr(r, "_build_agent")

    def test_build_agent_constructs_with_store(self, real_credential_store):
        """_build_agent() constructs a pydantic-ai Agent when the store has a key."""
        if not real_credential_store.has("google-1"):
            pytest.skip("no Google API key in credential store")
        from koan.memory.retrieval.reflect import _build_agent
        agent = _build_agent()
        assert agent is not None
