# Lightweight async LLM client for mechanical text generation.
# Used for summaries, query decomposition, synthesis -- not coding agents.
# M4: model selection was driven by the 'memory_llm' binding in the active
# provider config. This module now takes an explicit ModelSpec so no module
# global is read.

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from ..logger import get_logger

if TYPE_CHECKING:
    from ..types import ModelSpec

log = get_logger("memory.llm")


async def generate(prompt: str, model: "ModelSpec", system: str = "") -> str:
    """Call the LLM and return the text response.

    Model selection: the passed memory_llm ModelSpec, self-contained with its
    baked api_key. No module global is read.

    Inference settings: temperature 0.0 (deterministic for summaries).
    Thinking and caching settings are baked into the spec at flatten time.
    """
    from ..agents.adapter import build_model

    log.info(
        "generate provider=%s model=%s prompt_len=%d system_len=%d",
        model.provider, model.model, len(prompt), len(system),
    )
    built_model = build_model(model, api_key=model.api_key, region=model.region, base_url=model.base_url)
    agent: Agent[None, str] = Agent(
        model=built_model,
        model_settings={**model.settings, "temperature": 0.0},
        output_type=str,
        **({"system_prompt": system} if system else {}),
    )
    result = await agent.run(prompt)
    text = result.output or ""
    log.info("generate complete response_len=%d", len(text))
    return text
