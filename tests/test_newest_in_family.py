# Tests for the pure resolve_families function over the curated catalog (M2).
#
# M2: the async resolve_newest_in_family (live-list I/O), NewestResolution,
# NewestInFamilyUnavailable, apply_newest_resolution, _parse_family, and
# _order_model_ids_by_version are deleted. resolve_families is now a pure
# function over _BASE_CATALOG in koan.models.capabilities.

from __future__ import annotations

from koan.agents.newest_in_family import FamilyPin, resolve_families


def test_resolve_families_returns_one_pin_per_family():
    """resolve_families returns one FamilyPin per distinct family in _BASE_CATALOG."""
    pins = resolve_families()
    families = [p.family for p in pins]
    # No duplicates: one pin per family.
    assert len(families) == len(set(families)), "duplicate family pins"
    # The catalog has multiple distinct families (anthropic, google, openai, voyage, amazon).
    assert len(pins) >= 5


def test_resolve_families_picks_newest_version():
    """The resolved pin is the newest version in each family (by version_key)."""
    from koan.models.capabilities import _BASE_CATALOG
    from koan.models.identity import ModelIdentity, version_key

    pins = resolve_families()
    by_family = {p.family: p for p in pins}

    # For each family, the pin's resolved canonical string should correspond to
    # the newest catalog entry by version_key.
    from collections import defaultdict
    groups: dict[str, list[ModelIdentity]] = defaultdict(list)
    for (vendor, family, version), caps in _BASE_CATALOG.items():
        kind = "embedding" if caps.embedding_dims else "chat"
        groups[family].append(ModelIdentity(vendor=vendor, family=family, version=version, kind=kind))

    for family, members in groups.items():
        newest = sorted(members, key=version_key, reverse=True)[0]
        from koan.models.identity import canonical
        assert by_family[family].resolved == canonical(newest), (
            f"family {family}: expected newest {canonical(newest)}, got {by_family[family].resolved}"
        )


def test_resolve_families_is_pure():
    """Calling resolve_families twice yields the same family/resolved (modulo date in resolved_from)."""
    pins1 = resolve_families()
    pins2 = resolve_families()
    # family and resolved must be identical; only the date stamp in resolved_from may differ.
    assert [p.family for p in pins1] == [p.family for p in pins2]
    assert [p.resolved for p in pins1] == [p.resolved for p in pins2]


def test_resolve_families_sorted_by_family_name():
    """Output is sorted by family name (stable regardless of catalog iteration order)."""
    pins = resolve_families()
    families = [p.family for p in pins]
    assert families == sorted(families), "family pins not sorted by family name"


def test_resolve_families_with_explicit_catalog():
    """resolve_families accepts an explicit catalog and groups it, not just _BASE_CATALOG."""
    from koan.models.capabilities import _curated
    from koan.models.identity import canonical

    catalog = {
        ("anthropic", "claude-sonnet", "4.0"): _curated(
            context_window=200_000, max_output=32_768, thinking_modes=("low", "medium"),
        ),
        ("anthropic", "claude-sonnet", "4.5"): _curated(
            context_window=200_000, max_output=32_768, thinking_modes=("low", "medium"),
        ),
        ("openai", "gpt-4o", "1"): _curated(
            context_window=128_000, max_output=16_384, thinking_modes=(),
        ),
    }
    pins = resolve_families(catalog)
    by_family = {p.family: p for p in pins}
    assert set(by_family) == {"claude-sonnet", "gpt-4o"}
    # Newest in claude-sonnet is 4.5.
    from koan.models.identity import ModelIdentity
    assert by_family["claude-sonnet"].resolved == canonical(
        ModelIdentity(vendor="anthropic", family="claude-sonnet", version="4.5")
    )


def test_family_pin_is_frozen_dataclass():
    """FamilyPin is a frozen dataclass (immutable)."""
    pins = resolve_families()
    assert pins, "expected at least one pin"
    pin = pins[0]
    try:
        pin.family = "mutated"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("FamilyPin should be frozen (immutable)")