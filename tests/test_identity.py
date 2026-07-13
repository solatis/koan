# Tests for koan.models.identity.

from __future__ import annotations

import pytest

from koan.models.identity import (
    ModelIdentity,
    Unresolved,
    canonical,
    order_by_version,
    version_key,
)


class TestModelIdentity:
    def test_construction_with_all_fields(self) -> None:
        """ModelIdentity stores all fields and is frozen."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929", "chat")
        assert ident.vendor == "anthropic"
        assert ident.family == "claude-sonnet"
        assert ident.version == "4.5"
        assert ident.snapshot == "20250929"
        assert ident.kind == "chat"
        with pytest.raises(Exception):
            ident.vendor = "openai"  # frozen dataclass

    def test_construction_defaults(self) -> None:
        """snapshot defaults to None and kind defaults to chat."""
        ident = ModelIdentity("voyage", "voyage-4-large", "1")
        assert ident.snapshot is None
        assert ident.kind == "chat"

    def test_embedding_kind(self) -> None:
        """An embedding identity carries kind='embedding'."""
        ident = ModelIdentity("voyage", "voyage-4-large", "1", kind="embedding")
        assert ident.kind == "embedding"


class TestCanonical:
    def test_with_snapshot(self) -> None:
        """canonical produces vendor/family-version@snapshot when snapshot is set."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "4.5", "20250929")
        assert canonical(ident) == "anthropic/claude-sonnet-4.5@20250929"

    def test_without_snapshot(self) -> None:
        """canonical omits the @snapshot segment when snapshot is None."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "4.5")
        assert canonical(ident) == "anthropic/claude-sonnet-4.5"

    def test_embedding_canonical(self) -> None:
        """canonical works for embedding identities (voyage family == model id)."""
        ident = ModelIdentity("voyage", "voyage-4-large", "1", kind="embedding")
        assert canonical(ident) == "voyage/voyage-4-large-1"


class TestVersionKey:
    def test_dotted_version(self) -> None:
        """version_key splits dotted versions into numeric tuples."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "4.5")
        assert version_key(ident) == (4, 5)

    def test_dashed_version(self) -> None:
        """version_key splits dashed versions into numeric tuples."""
        ident = ModelIdentity("anthropic", "claude-opus", "4-0")
        assert version_key(ident) == (4, 0)

    def test_datestamp_skipped(self) -> None:
        """version_key skips date-stamps (>5 digits) so they don't outrank 'latest'."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "20250929")
        assert version_key(ident) == ()

    def test_single_digit(self) -> None:
        """A single-segment version yields a one-element tuple."""
        ident = ModelIdentity("anthropic", "claude-fable", "5")
        assert version_key(ident) == (5,)


class TestOrderByVersion:
    def test_newest_first(self) -> None:
        """order_by_version returns identities sorted newest-first."""
        v4 = ModelIdentity("anthropic", "claude-sonnet", "4")
        v45 = ModelIdentity("anthropic", "claude-sonnet", "4.5")
        v5 = ModelIdentity("anthropic", "claude-sonnet", "5")
        result = order_by_version([v4, v5, v45])
        assert result == [v5, v45, v4]


class TestUnresolved:
    def test_construction_and_fields(self) -> None:
        """Unresolved is a NamedTuple with wire_id and route fields."""
        u = Unresolved("garbage-id", "anthropic")
        assert u.wire_id == "garbage-id"
        assert u.route == "anthropic"

    def test_modelfref_accepts_both(self) -> None:
        """ModelRef accepts both ModelIdentity and Unresolved instances."""
        ident = ModelIdentity("anthropic", "claude-sonnet", "4.5")
        u = Unresolved("garbage-id", "anthropic")
        refs = [ident, u]  # type: ignore[list-item]
        assert isinstance(refs[0], ModelIdentity)
        assert isinstance(refs[1], Unresolved)