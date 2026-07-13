# Negative-presence tests: verify deleted modules and symbols are absent (M2).
#
# These tests assert that the superseded modules and symbols are truly gone,
# not just unused. They guard against accidental reintroduction.

from __future__ import annotations

import importlib

import pytest


def test_recognition_module_removed() -> None:
    """koan.agents.recognition is not importable (superseded by koan.models.codecs)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.agents.recognition")


def test_capability_resolver_module_removed() -> None:
    """koan.agents.capability_resolver is not importable (superseded by koan.models.capabilities)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.agents.capability_resolver")


def test_model_catalog_module_removed() -> None:
    """koan.agents.model_catalog is not importable (superseded by koan.models.capabilities + pricing)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("koan.agents.model_catalog")


def test_map_thinking_removed() -> None:
    """adapter.map_thinking is absent (superseded by dialects.apply_thinking)."""
    from koan.agents import adapter
    assert not hasattr(adapter, "map_thinking")


def test_provider_prefix_removed() -> None:
    """adapter._PROVIDER_PREFIX is absent (superseded by route registry)."""
    from koan.agents import adapter
    assert not hasattr(adapter, "_PROVIDER_PREFIX")


def test_caching_settings_removed() -> None:
    """adapter._caching_settings is absent (superseded by dialects.emit_cache_settings)."""
    from koan.agents import adapter
    assert not hasattr(adapter, "_caching_settings")


def test_resolved_capabilities_removed() -> None:
    """types.ResolvedCapabilities is absent (superseded by koan.models.capabilities.Capabilities)."""
    from koan import types
    assert not hasattr(types, "ResolvedCapabilities")


def test_provider_type_removed() -> None:
    """types.ProviderType is absent (superseded by route ids)."""
    from koan import types
    assert not hasattr(types, "ProviderType")


def test_all_provider_types_removed() -> None:
    """types.ALL_PROVIDER_TYPES is absent (superseded by koan.models.routes.route_ids)."""
    from koan import types
    assert not hasattr(types, "ALL_PROVIDER_TYPES")


def test_cache_read_expected_removed() -> None:
    """cache_read_expected is absent (superseded by ModelSpec.cache_expectation)."""
    from koan.agents import cache_guard
    assert not hasattr(cache_guard, "cache_read_expected")