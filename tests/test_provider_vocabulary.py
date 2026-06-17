"""Drift-guard: tie every derived provider table back to ALL_PROVIDER_TYPES.

The memory-0169 hazard is a MISSING reader -- a provider added to the vocabulary
that a peripheral dispatch table forgot -- causing a boot-crash rather than a
local test failure.  These guards catch the missing direction (the table omits a
provider the vocabulary has) as well as stray extras (the table has a provider
the vocabulary does not).

Written dynamically against ALL_PROVIDER_TYPES so M3's later lmstudio removal
needs no edit to this file.
"""

from __future__ import annotations

from koan.types import ALL_PROVIDER_TYPES, KEYLESS_PROVIDER_TYPES
from koan.agents.adapter import _PROVIDER_PREFIX, _KEY_REQUIRING_PROVIDERS
from koan.agents.model_catalog import PROVIDER_ID_MAP
from koan.web.app import _VALID_CONNECTION_TYPES, LISTING_CAPABLE

# voyage is embedding-only; excluded from chat-capable tables (build, listing)
# without being an error. The drift-guard uses subtraction rather than a
# hardcoded list so it stays accurate as providers are added or removed.
CHAT_PROVIDER_TYPES = set(ALL_PROVIDER_TYPES) - {"voyage"}


def test_valid_connection_types_matches_all_provider_types():
    """_VALID_CONNECTION_TYPES must equal ALL_PROVIDER_TYPES (bidirectional)."""
    assert set(_VALID_CONNECTION_TYPES) == set(ALL_PROVIDER_TYPES), (
        f"_VALID_CONNECTION_TYPES diverged from ALL_PROVIDER_TYPES: "
        f"extra={set(_VALID_CONNECTION_TYPES) - set(ALL_PROVIDER_TYPES)}, "
        f"missing={set(ALL_PROVIDER_TYPES) - set(_VALID_CONNECTION_TYPES)}"
    )


def test_provider_prefix_covers_all_chat_providers():
    """_PROVIDER_PREFIX must cover every chat provider (ALL_PROVIDER_TYPES minus voyage).

    A missing entry here raises unknown_provider at build time, which crashes the
    run rather than producing a graceful error.
    """
    assert set(_PROVIDER_PREFIX) == CHAT_PROVIDER_TYPES, (
        f"_PROVIDER_PREFIX diverged from CHAT_PROVIDER_TYPES: "
        f"extra={set(_PROVIDER_PREFIX) - CHAT_PROVIDER_TYPES}, "
        f"missing={CHAT_PROVIDER_TYPES - set(_PROVIDER_PREFIX)}"
    )


def test_key_requiring_providers_subset_of_chat_providers():
    """_KEY_REQUIRING_PROVIDERS must be a subset of CHAT_PROVIDER_TYPES and
    disjoint from KEYLESS_PROVIDER_TYPES.

    It is legitimately partial (bedrock authenticates differently and is not in
    this set), so only the subset/disjoint invariants are checked.
    """
    assert set(_KEY_REQUIRING_PROVIDERS) <= CHAT_PROVIDER_TYPES, (
        f"_KEY_REQUIRING_PROVIDERS contains non-chat-providers: "
        f"{set(_KEY_REQUIRING_PROVIDERS) - CHAT_PROVIDER_TYPES}"
    )
    assert set(_KEY_REQUIRING_PROVIDERS) & set(KEYLESS_PROVIDER_TYPES) == set(), (
        f"_KEY_REQUIRING_PROVIDERS and KEYLESS_PROVIDER_TYPES overlap: "
        f"{set(_KEY_REQUIRING_PROVIDERS) & set(KEYLESS_PROVIDER_TYPES)}"
    )


def test_listing_capable_subset_of_chat_providers():
    """LISTING_CAPABLE must be a subset of CHAT_PROVIDER_TYPES.

    It is legitimately partial (bedrock/voyage do not expose a list endpoint),
    so only the subset invariant is checked, not equality.
    """
    assert set(LISTING_CAPABLE) <= CHAT_PROVIDER_TYPES, (
        f"LISTING_CAPABLE contains non-chat-providers: "
        f"{set(LISTING_CAPABLE) - CHAT_PROVIDER_TYPES}"
    )


# -- Negative-presence guards (M3: lmstudio removed) --------------------------

def test_lmstudio_absent_from_vocabulary():
    """lmstudio must not appear in any provider dispatch table after M3 removal."""
    assert "lmstudio" not in ALL_PROVIDER_TYPES
    assert "lmstudio" not in _PROVIDER_PREFIX
    assert "lmstudio" not in _VALID_CONNECTION_TYPES
    assert "lmstudio" not in LISTING_CAPABLE
    assert "lmstudio" not in PROVIDER_ID_MAP


def test_keyless_provider_types_empty():
    """KEYLESS_PROVIDER_TYPES must be empty after M3 -- dormant seam, not dead code."""
    from koan.types import KEYLESS_PROVIDER_TYPES
    assert KEYLESS_PROVIDER_TYPES == frozenset()


def test_lmstudio_native_module_removed():
    """koan.agents.lmstudio_native must not be importable after M3 deletion."""
    import importlib
    try:
        importlib.import_module("koan.agents.lmstudio_native")
        raise AssertionError("koan.agents.lmstudio_native is still importable -- expected ModuleNotFoundError")
    except ModuleNotFoundError:
        pass  # expected
