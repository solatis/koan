# Unit tests for koan/agents/newest_in_family.py.
#
# All tests monkeypatch list_models_for_connection in the newest_in_family
# module so no real network calls are made.

from __future__ import annotations

import pytest

from koan.types import ConfiguredModel, Connection, ProviderModel


def _make_connection(type_: str = "anthropic", id_: str = "conn-1") -> Connection:
    """Build a minimal Connection for testing."""
    return Connection(id=id_, type=type_)


def _provider_model(model_id: str, provider: str = "anthropic") -> ProviderModel:
    """Build a minimal ProviderModel for testing."""
    return ProviderModel(provider=provider, model=model_id, display_name=model_id)


# -- resolve_newest_in_family -------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_newest_picks_newest_version(monkeypatch):
    """resolve_newest_in_family returns the newest versioned model in the family."""
    from koan.agents import newest_in_family as m

    models = [
        _provider_model("claude-sonnet-4-5"),
        _provider_model("claude-sonnet-4-0"),
        _provider_model("claude-haiku-4-0"),   # different family -- excluded
    ]

    async def fake_list(conn, store, timeout=8.0):
        return models

    monkeypatch.setattr(m, "list_models_for_connection", fake_list)

    res = await m.resolve_newest_in_family(_make_connection(), "claude-sonnet", None)

    assert res.model_id == "claude-sonnet-4-5"
    assert "claude-sonnet" in res.resolved_from
    assert "claude-sonnet-4-5" in res.resolved_from


@pytest.mark.asyncio
async def test_resolve_newest_resolved_from_format(monkeypatch):
    """resolved_from contains the family, a date token, and the pinned id."""
    import re
    from koan.agents import newest_in_family as m

    async def fake_list(conn, store, timeout=8.0):
        return [_provider_model("claude-opus-4-0")]

    monkeypatch.setattr(m, "list_models_for_connection", fake_list)

    res = await m.resolve_newest_in_family(_make_connection(), "claude-opus", None)

    # Format: "newest(<family>)@YYYY-MM-DD -> <model_id>"
    assert re.match(
        r"newest\(claude-opus\)@\d{4}-\d{2}-\d{2} -> claude-opus-4-0",
        res.resolved_from,
    )


@pytest.mark.asyncio
async def test_resolve_newest_empty_family_raises_unavailable(monkeypatch):
    """When no models match the family, NewestInFamilyUnavailable is raised."""
    from koan.agents import newest_in_family as m
    from koan.agents.newest_in_family import NewestInFamilyUnavailable

    async def fake_list(conn, store, timeout=8.0):
        return [_provider_model("claude-haiku-4-0")]

    monkeypatch.setattr(m, "list_models_for_connection", fake_list)

    with pytest.raises(NewestInFamilyUnavailable):
        await m.resolve_newest_in_family(_make_connection(), "claude-opus", None)


@pytest.mark.asyncio
async def test_resolve_newest_listing_error_propagates(monkeypatch):
    """ModelListingError from list_models_for_connection propagates unchanged."""
    from koan.agents import newest_in_family as m
    from koan.agents.model_listing import ModelListingError

    async def fake_list(conn, store, timeout=8.0):
        raise ModelListingError("bedrock does not support model listing")

    monkeypatch.setattr(m, "list_models_for_connection", fake_list)

    with pytest.raises(ModelListingError, match="bedrock"):
        await m.resolve_newest_in_family(
            _make_connection(type_="bedrock"), "amazon-nova-pro", None
        )


@pytest.mark.asyncio
async def test_resolve_newest_excludes_unrecognised_models(monkeypatch):
    """Models with unrecognised ids (family=None) are not counted as family members."""
    from koan.agents import newest_in_family as m
    from koan.agents.newest_in_family import NewestInFamilyUnavailable

    # Only an unrecognised id -- should not match "claude-sonnet".
    async def fake_list(conn, store, timeout=8.0):
        return [_provider_model("some-unknown-model-xyz")]

    monkeypatch.setattr(m, "list_models_for_connection", fake_list)

    with pytest.raises(NewestInFamilyUnavailable):
        await m.resolve_newest_in_family(_make_connection(), "claude-sonnet", None)


# -- resolve_families ---------------------------------------------------------


def test_resolve_families_groups_by_family():
    """resolve_families returns one FamilyPin per recognised family."""
    from koan.agents.newest_in_family import resolve_families

    model_ids = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-0",
        "claude-haiku-4-0",
    ]
    pins = resolve_families(model_ids)

    families = {p.family for p in pins}
    assert families == {"claude-sonnet", "claude-haiku"}


def test_resolve_families_picks_newest_per_family():
    """Each FamilyPin resolved field is the newest version in that family."""
    from koan.agents.newest_in_family import resolve_families

    model_ids = [
        "claude-sonnet-4-5",
        "claude-sonnet-4-0",
    ]
    pins = resolve_families(model_ids)
    assert len(pins) == 1
    assert pins[0].resolved == "claude-sonnet-4-5"


def test_resolve_families_resolved_from_format():
    """resolved_from follows 'newest(<family>)@YYYY-MM-DD -> <model_id>' format."""
    import re
    from koan.agents.newest_in_family import resolve_families

    pins = resolve_families(["claude-opus-4-0"])
    assert len(pins) == 1
    p = pins[0]
    assert re.match(
        r"newest\(claude-opus\)@\d{4}-\d{2}-\d{2} -> claude-opus-4-0",
        p.resolved_from,
    )


def test_resolve_families_skips_unrecognised():
    """Model ids whose family is None are excluded from grouping."""
    from koan.agents.newest_in_family import resolve_families

    pins = resolve_families(["some-unknown-model-xyz", "claude-haiku-4-0"])
    assert len(pins) == 1
    assert pins[0].family == "claude-haiku"


def test_resolve_families_empty_list_returns_empty():
    """Empty input yields no pins."""
    from koan.agents.newest_in_family import resolve_families

    assert resolve_families([]) == []


def test_resolve_families_sorted_by_family_name():
    """Result is sorted by family name for stable output."""
    from koan.agents.newest_in_family import resolve_families

    model_ids = [
        "claude-sonnet-4-0",
        "claude-haiku-4-0",
        "claude-opus-4-0",
    ]
    pins = resolve_families(model_ids)
    names = [p.family for p in pins]
    assert names == sorted(names)


# -- apply_newest_resolution --------------------------------------------------


def test_apply_newest_resolution_sets_fields():
    """apply_newest_resolution mutates model_id and resolved_from on ConfiguredModel."""
    from koan.agents.newest_in_family import NewestResolution, apply_newest_resolution

    cm = ConfiguredModel(id="cm-1", connection_id="conn-1", model_id="claude-sonnet-4-0")
    res = NewestResolution(
        model_id="claude-sonnet-4-5",
        resolved_from="newest(claude-sonnet)@2026-06-09 -> claude-sonnet-4-5",
    )

    result = apply_newest_resolution(cm, res)

    assert result is cm  # returns the same object
    assert cm.model_id == "claude-sonnet-4-5"
    assert cm.resolved_from == "newest(claude-sonnet)@2026-06-09 -> claude-sonnet-4-5"


def test_apply_newest_resolution_overwrites_existing_resolved_from():
    """apply_newest_resolution replaces a pre-existing resolved_from value."""
    from koan.agents.newest_in_family import NewestResolution, apply_newest_resolution

    cm = ConfiguredModel(
        id="cm-2",
        connection_id="conn-1",
        model_id="claude-sonnet-4-0",
        resolved_from="newest(claude-sonnet)@2026-01-01 -> claude-sonnet-4-0",
    )
    res = NewestResolution(
        model_id="claude-sonnet-4-5",
        resolved_from="newest(claude-sonnet)@2026-06-09 -> claude-sonnet-4-5",
    )

    apply_newest_resolution(cm, res)

    assert cm.model_id == "claude-sonnet-4-5"
    assert "2026-06-09" in cm.resolved_from
