# M7 provider fan-out: build_model / build_model_settings / build_usage_limits
# across all providers. The pure mapping functions (map_thinking, _caching_settings)
# were deleted in M2 (superseded by dialects.apply_thinking / dialects.emit_cache_settings).
# build_model is tested via a helper that constructs ModelSpec with a real Offering.
#
# M2: _spec() helper now takes an offering (constructed via resolve_offering).
# cache_ttl_for tests moved to test_dialects.py (function relocated to dialects.py).

from __future__ import annotations

import pytest

from koan.agents import adapter
from koan.agents.base import AgentError
from koan.types import CachingPolicy, ModelSpec


def _offering(route_id: str, model: str = "test-model"):
    """Build a real Offering via resolve_offering for adapter tests."""
    from koan.models.offering import resolve_offering
    return resolve_offering(route_id, model)


def _spec(route_id: str, model: str = "test-model", thinking="disabled",
          caching=None, settings=None, offering=None):
    """Build a minimal ModelSpec for adapter tests.

    Uses resolve_offering to construct an Offering so the delegating provider/model
    properties work. Pass offering=None + a fake route_id to create a spec with
    no offering (for unknown-provider tests).
    """
    if offering is None:
        try:
            offering = _offering(route_id, model)
        except Exception:
            offering = None
    return ModelSpec(
        offering=offering,
        thinking=thinking,
        settings=settings or {},
        caching=caching or CachingPolicy(),
    )


# -- caching (via build_model_settings, which is now a pass-through) -----------


def test_caching_off_emits_nothing():
    """CachingPolicy(mode='off') -- the settings dict is empty (no cache keys baked)."""
    s = adapter.build_model_settings(
        _spec("anthropic", model="claude-opus-4-0", caching=CachingPolicy(mode="off"))
    )
    assert not any(k.startswith("anthropic_cache") for k in s)


def test_build_model_settings_merges_spec_settings_and_thinking():
    """build_model_settings returns the pre-baked settings from spec.settings.

    Thinking and caching are baked into spec.settings at flatten time by
    build_resolved_model; build_model_settings is a trivial pass-through.
    """
    pre_baked = {"temperature": 0.2, "thinking": "low"}
    s = adapter.build_model_settings(
        _spec("openai", model="gpt-4o", thinking="low", settings=pre_baked)
    )
    assert s["temperature"] == 0.2
    assert s["thinking"] == "low"


def test_build_model_settings_never_injects_temperature():
    """build_model_settings does not inject a temperature key when the spec carries none.

    Regression guard: Anthropic returns 400 ('temperature may only be set to 1
    when thinking is enabled or in adaptive mode') when temperature is forced
    alongside a thinking spec. build_model_settings must be a pure pass-through
    that never adds temperature on its own.
    """
    baked = {"thinking": "medium"}
    s = adapter.build_model_settings(
        _spec("anthropic", model="claude-sonnet-4-5", settings=baked)
    )
    assert s["thinking"] == "medium"
    assert "temperature" not in s


# -- build_model ---------------------------------------------------------------


def test_build_model_no_offering_raises_agenterror():
    """build_model raises unknown_provider when the spec has no offering."""
    spec = ModelSpec(offering=None, thinking="disabled")
    with pytest.raises(AgentError) as exc:
        adapter.build_model(spec)
    assert exc.value.diagnostic.code == "unknown_provider"


def test_build_model_key_requiring_provider_no_key_raises():
    """build_model raises missing_credentials for google/anthropic/openai without api_key."""
    for provider in ("google", "anthropic", "openai"):
        with pytest.raises(AgentError) as exc:
            adapter.build_model(_spec(provider, model="test-model"))
        assert exc.value.diagnostic.code == "missing_credentials"


def test_build_model_bedrock_no_region_raises():
    """build_model raises missing_region for bedrock-converse when no region is supplied.

    The offering's locality is None for a bedrock model id without a geo prefix,
    so the missing_region gate fires.
    """
    with pytest.raises(AgentError) as exc:
        adapter.build_model(_spec("bedrock-converse", model="anthropic.claude-opus-4-0-v1:0"))
    assert exc.value.diagnostic.code == "missing_region"


def test_build_model_bedrock_no_key_raises_missing_credentials():
    """build_model raises missing_credentials for bedrock-converse when no api_key is supplied.

    Bedrock requires an explicit long-lived API key; the AWS credential chains
    is not used. A region without a key is not sufficient.
    """
    with pytest.raises(AgentError) as exc:
        adapter.build_model(
            _spec("bedrock-converse", model="us.amazon.nova-pro-v1:0"),
            region="us-east-1",
        )
    assert exc.value.diagnostic.code == "missing_credentials"


@pytest.mark.parametrize(
    "route_id,model_cls_path",
    [
        ("google", "pydantic_ai.models.google.GoogleModel"),
        ("anthropic", "pydantic_ai.models.anthropic.AnthropicModel"),
        ("openai", "pydantic_ai.models.openai.OpenAIChatModel"),
        ("bedrock-converse", "pydantic_ai.models.bedrock.BedrockConverseModel"),
    ],
)
def test_build_model_with_api_key_builds_explicit_model(route_id, model_cls_path):
    """build_model with api_key constructs a provider-typed model (no infer_model).

    region='us-east-1' is passed for all providers to satisfy the bedrock
    missing_region gate; non-bedrock providers ignore the region kwarg.
    """
    import importlib
    model = adapter.build_model(
        _spec(route_id, model="test-model"),
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
        _spec("bedrock-converse", model="us.anthropic.claude-opus-4-0-v1:0"),
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
        _spec("openai", model="gpt-4o"),
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
        _spec("openrouter", model="anthropic/claude-sonnet-4-5"),
        api_key="sk-or-test",
    )
    assert isinstance(model, OpenRouterModel)


def test_build_model_openrouter_missing_key_raises():
    """build_model raises missing_credentials for openrouter when api_key is None."""
    with pytest.raises(AgentError) as exc_info:
        adapter.build_model(_spec("openrouter", model="anthropic/claude-sonnet-4-5"))
    assert exc_info.value.diagnostic.code == "missing_credentials"


# -- Gateway unit tests --------------------------------------------------------


def test_cache_tier_for_role_long_roles():
    """orchestrator, executor, planner, and intake all resolve to the 'long' cache tier."""
    from koan.types import cache_tier_for_role
    for role in ("orchestrator", "executor", "planner", "intake"):
        assert cache_tier_for_role(role) == "long", f"expected long for {role!r}"


def test_cache_tier_for_role_short_roles():
    """reviewer and scout resolve to the 'short' cache tier."""
    from koan.types import cache_tier_for_role
    for role in ("reviewer", "scout"):
        assert cache_tier_for_role(role) == "short", f"expected short for {role!r}"


def test_cache_tier_for_role_unknown_defaults_to_long():
    """Any unmapped role falls back to 'long' (safe default for unknown roles)."""
    from koan.types import cache_tier_for_role
    assert cache_tier_for_role("unknown-future-role") == "long"  # type: ignore[arg-type]