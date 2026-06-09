# Unit tests for koan.credentials: FileKeyBackend, Fernet round-trip,
# CredentialStore operations, and config round-trip.
#
# M1: SEED_ENV_KEYS and seed_from_env removed (brief D13 -- credentials are
# fully manual).  Credentials are keyed by connection id.
# M4: the type-alias bridge (resolve("google")/resolve("voyage") falling through
# to the first connection of that type) is removed.  TestTypeAliasBridge now
# asserts the alias is gone: type-keyed resolve returns None; connection-id
# lookup works.

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path

import pytest
import yaml

from koan.config import KoanConfig, load_koan_config, save_koan_config
from koan.credentials import (
    SCHEME,
    CredentialStore,
    FileKeyBackend,
    decrypt_secret,
    encrypt_secret,
    get_key_backend,
    set_active_credential_store,
    active_credential_store,
)
from koan.types import Connection


# ---------------------------------------------------------------------------
# FileKeyBackend
# ---------------------------------------------------------------------------

class TestFileKeyBackend:
    def test_generates_key_when_absent(self, tmp_path, monkeypatch):
        """load_key creates a new Fernet key and writes it when master.key is absent."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        backend = FileKeyBackend()
        key = backend.load_key()
        assert key_path.exists()
        assert len(key) > 0
        # Key should be valid Fernet (44 bytes URL-safe base64)
        from cryptography.fernet import Fernet
        Fernet(key)  # raises if invalid

    def test_key_file_is_mode_0600(self, tmp_path, monkeypatch):
        """Generated master.key is written with mode 0600."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        FileKeyBackend().load_key()
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600

    def test_reuses_existing_key(self, tmp_path, monkeypatch):
        """load_key returns the same key on subsequent calls (never regenerates)."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        backend = FileKeyBackend()
        key1 = backend.load_key()
        key2 = backend.load_key()
        assert key1 == key2

    def test_does_not_regenerate_existing_key(self, tmp_path, monkeypatch):
        """load_key uses the existing file when present without regenerating it."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        # Generate once
        backend = FileKeyBackend()
        original_key = backend.load_key()
        # A second backend instance should return the same key
        backend2 = FileKeyBackend()
        assert backend2.load_key() == original_key


# ---------------------------------------------------------------------------
# encrypt_secret / decrypt_secret
# ---------------------------------------------------------------------------

class TestEnvelopeHelpers:
    def _backend(self, tmp_path, monkeypatch):
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        return FileKeyBackend()

    def test_round_trip(self, tmp_path, monkeypatch):
        """encrypt_secret -> decrypt_secret returns the original plaintext."""
        backend = self._backend(tmp_path, monkeypatch)
        envelope = encrypt_secret("my-secret-key", backend)
        assert envelope["scheme"] == SCHEME
        assert "ciphertext" in envelope
        assert "my-secret-key" not in envelope["ciphertext"]
        plaintext = decrypt_secret(envelope, backend)
        assert plaintext == "my-secret-key"

    def test_ciphertext_does_not_contain_plaintext(self, tmp_path, monkeypatch):
        """The ciphertext in the envelope does not contain the plaintext."""
        backend = self._backend(tmp_path, monkeypatch)
        secret = "super-secret-api-key-12345"
        envelope = encrypt_secret(secret, backend)
        assert secret not in json.dumps(envelope)

    def test_decrypt_rejects_unknown_scheme(self, tmp_path, monkeypatch):
        """decrypt_secret raises ValueError for an unrecognised scheme tag."""
        backend = self._backend(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="unknown credential scheme"):
            decrypt_secret({"scheme": "plaintext", "ciphertext": "abc"}, backend)


# ---------------------------------------------------------------------------
# CredentialStore
# ---------------------------------------------------------------------------

def _make_store(tmp_path, monkeypatch, credentials=None, connections=None):
    """Build a CredentialStore over a fresh tmp KoanConfig with a tmp master key."""
    key_path = tmp_path / "master.key"
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
    config = KoanConfig(
        credentials=credentials or {},
        connections=connections or [],
    )
    backend = FileKeyBackend()
    return CredentialStore(config, backend), config, backend


class TestCredentialStore:
    def test_resolve_returns_none_for_absent_key(self, tmp_path, monkeypatch):
        """resolve() returns None for a connection id not in the store."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        assert store.resolve("anthropic-direct") is None

    def test_has_returns_false_for_absent_key(self, tmp_path, monkeypatch):
        """has() returns False for a connection id not in the store."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        assert not store.has("anthropic-direct")

    def test_set_then_resolve_by_connection_id(self, tmp_path, monkeypatch):
        """set() followed by resolve() returns the stored plaintext by connection id."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        store.set("google-direct", "my-google-key")
        assert store.resolve("google-direct") == "my-google-key"
        assert store.has("google-direct")

    def test_remove_clears_key(self, tmp_path, monkeypatch):
        """remove() clears the key from both cache and config."""
        store, config, _ = _make_store(tmp_path, monkeypatch)
        store.set("voyage-1", "my-voyage-key")
        store.remove("voyage-1")
        assert store.resolve("voyage-1") is None
        assert "voyage-1" not in config.credentials

    def test_remove_is_idempotent(self, tmp_path, monkeypatch):
        """remove() on an absent key does not raise."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        store.remove("nonexistent")  # must not raise

    def test_available_providers(self, tmp_path, monkeypatch):
        """available_providers() returns sorted list of keys with a stored secret."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        store.set("voyage-embed", "v-key")
        store.set("anthropic-direct", "a-key")
        assert store.available_providers() == ["anthropic-direct", "voyage-embed"]

    def test_corrupt_envelope_pruned_on_init(self, tmp_path, monkeypatch):
        """A corrupt envelope is pruned during store construction: removed from config
        and the pruned flag set, while valid envelopes are unaffected."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        # Set up a corrupt envelope alongside a valid one
        backend = FileKeyBackend()
        valid_envelope = encrypt_secret("real-key", backend)
        corrupt_envelope = {"scheme": SCHEME, "ciphertext": "notvalidbase64!!"}
        config = KoanConfig(credentials={
            "google-direct": valid_envelope,
            "voyage-embed": corrupt_envelope,
        })
        # Must not raise; must prune the corrupt envelope
        store = CredentialStore(config, backend)
        assert store.resolve("google-direct") == "real-key"
        assert store.resolve("voyage-embed") is None
        # Per-envelope pruning: corrupt entry removed, valid entry kept.
        assert "voyage-embed" not in config.credentials
        assert "google-direct" in config.credentials
        assert store.pruned is True

    def test_pruned_false_on_clean_init(self, tmp_path, monkeypatch):
        """A store constructed over only valid envelopes has pruned == False."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        backend = FileKeyBackend()
        valid_envelope = encrypt_secret("valid-key", backend)
        config = KoanConfig(credentials={"openai-direct": valid_envelope})
        store = CredentialStore(config, backend)
        assert store.pruned is False
        assert "openai-direct" in config.credentials

    def test_orphaned_envelope_self_heals(self, tmp_path, monkeypatch):
        """An orphaned (undecryptable) envelope is pruned at construction and the
        provider can then be re-added via store.set(), restoring availability."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        backend = FileKeyBackend()
        # Write a corrupt envelope -- simulates an envelope whose key is gone.
        orphaned_envelope = {"scheme": SCHEME, "ciphertext": "notvalidbase64!!"}
        config = KoanConfig(credentials={"google-direct": orphaned_envelope})
        store = CredentialStore(config, backend)
        # Step 1: prune the orphan.
        assert store.pruned is True
        assert "google-direct" not in config.credentials
        # Step 2: re-add via explicit set (env-seeding removed in M1).
        store.set("google-direct", "fresh-key")
        assert store.resolve("google-direct") == "fresh-key"

    def test_systemic_key_failure_does_not_prune(self, tmp_path, monkeypatch):
        """A malformed/non-Fernet master.key causes a systemic failure: the cache
        is empty but NO envelope is pruned from config, and pruned stays False."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        # Write garbage bytes -- not a valid Fernet key.
        key_path.write_bytes(b"this-is-not-a-fernet-key")
        backend = FileKeyBackend()
        # Build a config with a plausible-looking envelope (scheme tag correct).
        stored_envelope = {"scheme": SCHEME, "ciphertext": "somebase64token=="}
        config = KoanConfig(credentials={"anthropic-direct": stored_envelope})
        store = CredentialStore(config, backend)
        # Systemic key failure: cache empty but no pruning happened.
        assert store.pruned is False
        assert "anthropic-direct" in config.credentials
        assert store.resolve("anthropic-direct") is None

    def test_set_writes_envelope_to_config(self, tmp_path, monkeypatch):
        """set() writes an encrypted envelope to config.credentials."""
        store, config, _ = _make_store(tmp_path, monkeypatch)
        store.set("openai-direct", "openai-key")
        envelope = config.credentials.get("openai-direct", {})
        assert envelope.get("scheme") == SCHEME
        assert "openai-key" not in envelope.get("ciphertext", "")


# ---------------------------------------------------------------------------
# Type-alias bridge removed (M4 cutover)
# ---------------------------------------------------------------------------

class TestTypeAliasRemoved:
    """M4: the type-alias bridge is gone.  Type-keyed resolve() returns None;
    connection-id lookup works as the sole path."""

    def _make_store_with_connection(self, tmp_path, monkeypatch, conn_type, conn_id, secret):
        """Build a store with one connection and one credential keyed by connection id."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        backend = FileKeyBackend()
        conn = Connection(id=conn_id, type=conn_type)
        config = KoanConfig(connections=[conn])
        store = CredentialStore(config, backend)
        store.set(conn_id, secret)
        return store

    def test_resolve_by_connection_id_works(self, tmp_path, monkeypatch):
        """resolve() returns the secret when called with the connection id."""
        store = self._make_store_with_connection(
            tmp_path, monkeypatch, "google", "google-direct", "g-key"
        )
        assert store.resolve("google-direct") == "g-key"

    def test_resolve_by_type_string_returns_none(self, tmp_path, monkeypatch):
        """resolve('google') returns None -- type-alias bridge removed in M4."""
        store = self._make_store_with_connection(
            tmp_path, monkeypatch, "google", "google-direct", "g-key"
        )
        # Type-string key is not a connection id; no alias fallthrough.
        assert store.resolve("google") is None

    def test_has_by_connection_id_works(self, tmp_path, monkeypatch):
        """has() returns True when called with the connection id."""
        store = self._make_store_with_connection(
            tmp_path, monkeypatch, "voyage", "voyage-embed", "v-key"
        )
        assert store.has("voyage-embed") is True

    def test_has_by_type_string_returns_false(self, tmp_path, monkeypatch):
        """has('voyage') returns False -- type-alias bridge removed in M4."""
        store = self._make_store_with_connection(
            tmp_path, monkeypatch, "voyage", "voyage-embed", "v-key"
        )
        assert store.has("voyage") is False

    def test_unknown_key_returns_none(self, tmp_path, monkeypatch):
        """resolve() returns None for a key not in the cache."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        assert store.resolve("bedrock") is None
        assert store.has("bedrock") is False


# ---------------------------------------------------------------------------
# Module-level active store
# ---------------------------------------------------------------------------

class TestActiveStore:
    def test_active_store_raises_when_unset(self, monkeypatch):
        """active_credential_store raises RuntimeError when not initialized."""
        monkeypatch.setattr("koan.credentials._ACTIVE", None)
        with pytest.raises(RuntimeError, match="Active credential store is not initialized"):
            active_credential_store()

    def test_set_then_active(self, tmp_path, monkeypatch):
        """set_active_credential_store makes the store retrievable."""
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
        monkeypatch.setattr("koan.credentials._ACTIVE", None)
        config = KoanConfig()
        backend = FileKeyBackend()
        store = CredentialStore(config, backend)
        set_active_credential_store(store)
        assert active_credential_store() is store


# ---------------------------------------------------------------------------
# Config round-trip
# ---------------------------------------------------------------------------

class TestConfigRoundTrip:
    @pytest.mark.anyio
    async def test_credentials_survive_save_load(self, tmp_path, monkeypatch):
        """Credentials written to config.yaml round-trip through save/load."""
        config_path = tmp_path / "config.yaml"
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

        backend = FileKeyBackend()
        config = KoanConfig()
        store = CredentialStore(config, backend)
        store.set("google-direct", "my-plaintext-key")

        await save_koan_config(config)
        loaded_config = await load_koan_config()

        # Reconstruct store from loaded config with the same backend
        store2 = CredentialStore(loaded_config, backend)
        assert store2.resolve("google-direct") == "my-plaintext-key"

    @pytest.mark.anyio
    async def test_plaintext_not_in_config_file(self, tmp_path, monkeypatch):
        """The plaintext secret must not appear in the raw config.yaml bytes."""
        config_path = tmp_path / "config.yaml"
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

        backend = FileKeyBackend()
        config = KoanConfig()
        store = CredentialStore(config, backend)
        store.set("anthropic-direct", "very-secret-anthropic-key")

        await save_koan_config(config)
        raw = config_path.read_bytes()
        assert b"very-secret-anthropic-key" not in raw

    @pytest.mark.anyio
    async def test_credentials_envelope_in_yaml(self, tmp_path, monkeypatch):
        """Saved config.yaml contains a 'credentials' object with fernet envelopes."""
        config_path = tmp_path / "config.yaml"
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

        backend = FileKeyBackend()
        config = KoanConfig()
        store = CredentialStore(config, backend)
        store.set("voyage-embed", "voyage-key")

        await save_koan_config(config)
        data = yaml.safe_load(config_path.read_text())
        assert "credentials" in data
        assert "voyage-embed" in data["credentials"]
        assert data["credentials"]["voyage-embed"]["scheme"] == SCHEME
        assert "ciphertext" in data["credentials"]["voyage-embed"]

    def test_seed_from_env_absent(self, tmp_path, monkeypatch):
        """seed_from_env no longer exists on CredentialStore (brief D13)."""
        store, _, _ = _make_store(tmp_path, monkeypatch)
        assert not hasattr(store, "seed_from_env"), (
            "seed_from_env must not exist on CredentialStore after M1"
        )
