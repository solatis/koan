# Smoke tests confirming the memory module runs under pydantic-ai v2.0.0b6.
# The live Gemini LLM smoke tests were removed when memory-specific LLM bindings
# were eliminated (LLM tiers now resolve from the active preset's cheap/standard
# slots). The import-only test below remains as a lightweight check.

from __future__ import annotations


class TestReflectAgentV2Import:
    def test_reflect_imports_cleanly(self):
        """koan.memory.retrieval.reflect imports without error."""
        import koan.memory.retrieval.reflect as r
        assert hasattr(r, "run_reflect_agent")
        assert hasattr(r, "ReflectResult")
        assert hasattr(r, "_build_agent")