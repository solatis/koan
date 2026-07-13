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

    Inference settings: model settings (thinking + caching, baked into the spec
    at flatten time) come from the spec via build_model_settings. Temperature is
    intentionally left to the provider/PydanticAI default -- no explicit
    temperature is set, avoiding the Anthropic 400 that occurs when temperature
    is forced to 0.0 alongside thinking/adaptive mode.
    """
    # Late-binding import so monkeypatching adapter attributes in tests is observed
    # at call time (same pattern used throughout the agent layer).
    from ..agents.adapter import build_model, build_model_settings, build_usage_limits

    log.info(
        "generate provider=%s model=%s prompt_len=%d system_len=%d",
        model.provider, model.model, len(prompt), len(system),
    )
    built_model = build_model(model, api_key=model.api_key, region=None, base_url=model.base_url)
    agent: Agent[None, str] = Agent(
        model=built_model,
        model_settings=build_model_settings(model),
        output_type=str,
        **({"system_prompt": system} if system else {}),
    )
    result = await agent.run(prompt, usage_limits=build_usage_limits())
    text = result.output or ""
    log.info("generate complete response_len=%d", len(text))
    return text
