# M7 provider fan-out: map_thinking / caching / build_model across all four
# providers. The pure mapping functions are tested directly; build_model is
# tested via a monkeypatched infer_model so no real provider credentials or
# network are needed (only the prefix-selection logic is under test here).
#
# M2: map_thinking and _caching_settings now take a ResolvedCapabilities argument;
# tests are updated to pass a minimal caps stub rather than using the old two-arg
# signature.

from __future__ import annotations

import pytest

from koan.agents import adapter
from koan.agents.base import AgentError
from koan.types import CachingPolicy, ModelSpec, ResolvedCapabilities


def _spec(provider, model="m", thinking="disabled", caching=None, settings=None):
    """Build a minimal ModelSpec for adapter tests."""
    return ModelSpec(
        provider=provider,
        model=model,
        thinking=thinking,
        settings=settings or {},
        caching=caching or CachingPolicy(),
    )


def _caps(
    thinking_shape="budget",
    thinking_modes=None,
    supports_prompt_caching=False,
):
    """Build a minimal ResolvedCapabilities stub for map_thinking / caching tests."""
    return ResolvedCapabilities(
        thinking_supported=thinking_shape != "none",
        thinking_modes=list(thinking_modes if thinking_modes is not None else ["low", "medium", "high"]),
        thinking_shape=thinking_shape,
        supports_web_search=False,
        supports_tools=True,
        supports_prompt_caching=supports_prompt_caching,
    )


# -- map_thinking --------------------------------------------------------------


def test_map_thinking_google_disabled_returns_empty():
    """Disabled mode always returns {} -- the caller never needs a special disable path."""
    caps = _caps("budget", thinking_modes=["low", "medium", "high"])
    assert adapter.map_thinking("google", caps, "disabled") == {}


def test_map_thinking_google_mode_not_in_caps_returns_empty():
    """A thinking mode not in caps.thinking_modes returns {} (unsupported)."""
    caps = _caps("budget", thinking_modes=["low"])
    assert adapter.map_thinking("google", caps, "high") == {}


def test_map_thinking_google_budget():
    """Google budget shape emits google_thinking_config with the token budget."""
    caps = _caps("budget", thinking_modes=["low", "medium", "high"])
    out = adapter.map_thinking("google", caps, "high")
    assert out["google_thinking_config"]["thinking_budget"] == 8192
    assert out["google_thinking_config"]["include_thoughts"] is True


def test_map_thinking_anthropic_budget():
    """Anthropic budget shape emits anthropic_thinking with type=enabled and budget_tokens."""
    caps = _caps("budget", thinking_modes=["medium", "high"])
    assert adapter.map_thinking("anthropic", caps, "disabled") == {}
    result = adapter.map_thinking("anthropic", caps, "medium")
    assert result == {"anthropic_thinking": {"type": "enabled", "budget_tokens": 2048}}


def test_map_thinking_anthropic_adaptive():
    """Anthropic adaptive shape emits anthropic_thinking with type=adaptive (no budget)."""
    caps = _caps("adaptive", thinking_modes=["low", "medium", "high"])
    result = adapter.map_thinking("anthropic", caps, "medium")
    assert result == {"anthropic_thinking": {"type": "adaptive"}}


def test_map_thinking_openai_effort():
    """OpenAI effort shape emits openai_reasoning_effort."""
    caps = _caps("effort", thinking_modes=["low", "medium", "high", "xhigh", "max"])
    assert adapter.map_thinking("openai", caps, "disabled") == {}
    assert adapter.map_thinking("openai", caps, "low") == {"openai_reasoning_effort": "low"}
    # xhigh/max collapse to high (OpenAI has no finer knob above high).
    assert adapter.map_thinking("openai", caps, "xhigh") == {"openai_reasoning_effort": "high"}


def test_map_thinking_bedrock_is_noop():
    """Bedrock has no portable thinking knob -- map_thinking returns {} for any mode."""
    caps = _caps("budget", thinking_modes=["high"])
    assert adapter.map_thinking("bedrock", caps, "high") == {}


def test_map_thinking_unknown_provider_returns_empty():
    """Unrecognized providers fall through gracefully (brief D5) rather than raising."""
    caps = _caps("budget", thinking_modes=["high"])
    assert adapter.map_thinking("cohere", caps, "high") == {}


# -- caching -------------------------------------------------------------------


def test_caching_off_emits_nothing():
    """CachingPolicy(mode='off') always suppresses cache settings."""
    s = adapter.build_model_settings(
        _spec("anthropic", model="claude-opus-4-0", caching=CachingPolicy(mode="off"))
    )
    assert not any(k.startswith("anthropic_cache") for k in s)


def test_caching_anthropic_auto_sets_ttl():
    """Anthropic auto mode emits cache_instructions and cache_tool_definitions with TTL."""
    s = adapter.build_model_settings(
        _spec("anthropic", model="claude-opus-4-0", caching=CachingPolicy(mode="auto", ttl="1h"))
    )
    assert s["anthropic_cache_instructions"] == "1h"
    assert s["anthropic_cache_tool_definitions"] == "1h"


def test_caching_google_openai_bedrock_noop():
    """Google/OpenAI/Bedrock do not emit anthropic cache settings (capability-gated)."""
    for provider in ("google", "openai", "bedrock"):
        s = adapter.build_model_settings(
            _spec(provider, caching=CachingPolicy(mode="auto"))
        )
        assert not any(k.startswith("anthropic_cache") for k in s)


def test_build_model_settings_merges_spec_settings_and_thinking():
    """build_model_settings merges user settings with capability-driven thinking.

    Uses an o1-mini model which the OpenAI profile recognises as a reasoning model
    (always-on thinking), ensuring thinking_modes is populated for the test.
    """
    # o1-mini is an always-on reasoning model; thinking_modes should include "low".
    s = adapter.build_model_settings(
        _spec("openai", model="o1-mini", thinking="low", settings={"temperature": 0.2})
    )
    assert s["temperature"] == 0.2
    assert s["openai_reasoning_effort"] == "low"


# -- build_model ---------------------------------------------------------------


def test_build_model_unknown_provider_raises_agenterror():
    with pytest.raises(AgentError):
        adapter.build_model(_spec("cohere"))


def test_build_model_key_requiring_provider_no_key_raises():
    """build_model raises missing_credentials for google/anthropic/openai without api_key."""
    for provider in ("google", "anthropic", "openai"):
        with pytest.raises(AgentError) as exc:
            adapter.build_model(_spec(provider, model="m"))
        assert exc.value.diagnostic.code == "missing_credentials"


def test_build_model_bedrock_no_region_raises():
    """build_model raises missing_region for bedrock when no region is supplied."""
    with pytest.raises(AgentError) as exc:
        adapter.build_model(_spec("bedrock", model="m"))
    assert exc.value.diagnostic.code == "missing_region"


def test_build_model_bedrock_no_key_raises_missing_credentials():
    """build_model raises missing_credentials for bedrock when no api_key is supplied.

    Bedrock requires an explicit long-lived API key; the AWS credential chain
    is not used.  A region without a key is not sufficient.
    """
    with pytest.raises(AgentError) as exc:
        adapter.build_model(_spec("bedrock", model="us.amazon.nova-pro-v1:0"), region="us-east-1")
    assert exc.value.diagnostic.code == "missing_credentials"


@pytest.mark.parametrize(
    "provider,model_cls_path",
    [
        ("google", "pydantic_ai.models.google.GoogleModel"),
        ("anthropic", "pydantic_ai.models.anthropic.AnthropicModel"),
        ("openai", "pydantic_ai.models.openai.OpenAIChatModel"),
        ("bedrock", "pydantic_ai.models.bedrock.BedrockConverseModel"),
    ],
)
def test_build_model_with_api_key_builds_explicit_model(provider, model_cls_path):
    """build_model with api_key constructs a provider-typed model (no infer_model).

    region='us-east-1' is passed for all providers to satisfy the bedrock
    missing_region gate; non-bedrock providers ignore the region kwarg.
    """
    import importlib
    model = adapter.build_model(
        _spec(provider, model="test-model"),
        api_key="test-key",
        region="us-east-1",
    )
    module_path, cls_name = model_cls_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    assert isinstance(model, cls)


def test_build_model_threads_region_and_base_url_bedrock(monkeypatch):
    """build_model passes region_name, api_key, and base_url into BedrockProvider.

    Monkeypatches the provider and model classes to capture constructor kwargs
    so we can assert the exact parameter names without real AWS credentials.
    """
    captured: dict = {}

    class _FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _FakeModel:
        def __init__(self, model, provider=None):
            pass

    monkeypatch.setattr("pydantic_ai.providers.bedrock.BedrockProvider", _FakeProvider)
    monkeypatch.setattr("pydantic_ai.models.bedrock.BedrockConverseModel", _FakeModel)
    adapter.build_model(
        _spec("bedrock", model="m"),
        api_key="k",
        region="us-west-2",
        base_url="https://ep",
    )
    assert captured == {"region_name": "us-west-2", "api_key": "k", "base_url": "https://ep"}


def test_build_model_threads_base_url_openai(monkeypatch):
    """build_model passes api_key and base_url into OpenAIProvider; no region key.

    Confirms that region/region_name is not forwarded to non-bedrock providers.
    """
    captured: dict = {}

    class _FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _FakeModel:
        def __init__(self, model, provider=None):
            pass

    monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", _FakeProvider)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIChatModel", _FakeModel)
    adapter.build_model(
        _spec("openai", model="gpt-4"),
        api_key="sk-test",
        base_url="https://proxy.example.com",
    )
    assert captured.get("api_key") == "sk-test"
    assert captured.get("base_url") == "https://proxy.example.com"
    assert "region" not in captured
    assert "region_name" not in captured

# -- openrouter ---------------------------------------------------------------


def test_build_model_openrouter_constructs_openrouter_model():
    """build_model for openrouter constructs an OpenRouterModel (offline, no network call).

    Confirms the dedicated library class is used rather than the OpenAI shim.
    """
    from pydantic_ai.models.openrouter import OpenRouterModel
    model = adapter.build_model(
        _spec("openrouter", model="anthropic/claude-3.5-sonnet"),
        api_key="sk-or-test",
    )
    assert isinstance(model, OpenRouterModel)


def test_build_model_openrouter_missing_key_raises():
    """build_model raises missing_credentials for openrouter when api_key is None."""
    with pytest.raises(AgentError) as exc_info:
        adapter.build_model(_spec("openrouter", model="anthropic/claude-3.5-sonnet"))
    assert exc_info.value.diagnostic.code == "missing_credentials"


def test_map_thinking_openrouter_returns_empty():
    """openrouter has conservative capabilities (thinking_modes=[]) -- map_thinking returns {}.

    The empty thinking_modes list triggers the first-line guard in map_thinking,
    so no explicit openrouter branch is needed (and none exists).
    """
    caps = _caps("none", thinking_modes=[])
    assert adapter.map_thinking("openrouter", caps, "medium") == {}
    assert adapter.map_thinking("openrouter", caps, "disabled") == {}
