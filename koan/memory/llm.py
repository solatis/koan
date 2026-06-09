# Lightweight async LLM client for mechanical text generation.
# Used for summaries, query decomposition, synthesis -- not coding agents.
# M4: model selection is now driven by the 'memory_llm' binding in the
# active provider config (set_active_provider_config must be called at startup).
# The KOAN_LLM_MODEL env var and the hardcoded DEFAULT_MODEL are removed.

from __future__ import annotations

from pydantic_ai import Agent

from ..logger import get_logger
from .bindings import resolve_memory_binding

log = get_logger("memory.llm")


async def generate(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    """Call the LLM and return the text response.

    Model selection: resolved from the 'memory_llm' binding in the active
    provider config.  set_active_provider_config and set_active_credential_store
    must have been called at process startup before any call to generate().

    Inference settings are fixed: temperature 0.0 (deterministic for summaries)
    and the caller-provided max_tokens.  M4 changes which model is selected,
    not the inference behavior.

    Raises RuntimeError if the memory_llm binding is not configured or the
    credential store has no key for its connection.
    """
    from ..agents.adapter import build_model
    from ..types import ModelSpec

    rmm = resolve_memory_binding("memory_llm")
    log.info(
        "generate provider=%s model=%s prompt_len=%d system_len=%d max_tokens=%d",
        rmm.provider_type, rmm.model_id, len(prompt), len(system), max_tokens,
    )
    model = build_model(
        ModelSpec(
            provider=rmm.provider_type,
            model=rmm.model_id,
            thinking="disabled",
        ),
        api_key=rmm.api_key,
        region=rmm.region,
        base_url=rmm.base_url,
    )
    agent: Agent[None, str] = Agent(
        model=model,
        model_settings={"temperature": 0.0, "max_tokens": max_tokens},
        output_type=str,
        **({"system_prompt": system} if system else {}),
    )
    result = await agent.run(prompt)
    text = result.output or ""
    log.info("generate complete response_len=%d", len(text))
    return text
