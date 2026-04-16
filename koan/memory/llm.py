# Lightweight async LLM client for mechanical text generation.
# Used for summaries, query decomposition, synthesis -- not coding agents.

from __future__ import annotations

import os

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-flash-lite-latest"


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required"
        )
    return key


def _model() -> str:
    return os.environ.get("KOAN_LLM_MODEL") or DEFAULT_MODEL


async def generate(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    """Call Gemini and return the text response.

    Configuration:
      - Model: via env var KOAN_LLM_MODEL (default "gemini-3-flash-lite")
      - API key: via env var GEMINI_API_KEY or GOOGLE_API_KEY
      - Temperature: 0.0 (deterministic for summaries)

    Raises RuntimeError if the API key is not set or the call fails.
    """
    client = genai.Client(api_key=_api_key())
    config = types.GenerateContentConfig(
        system_instruction=system or None,
        temperature=0.0,
        max_output_tokens=max_tokens,
    )
    response = await client.aio.models.generate_content(
        model=_model(),
        contents=prompt,
        config=config,
    )
    return response.text or ""
