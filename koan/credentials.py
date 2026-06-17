# Centralized encrypted credential store for koan.
#
# All provider API keys are stored here, encrypted at rest with Fernet
# (AES-128-CBC + HMAC-SHA256) under a master key. The master key is loaded
# from a pluggable KeyBackend; only the file backend is implemented now.
#
# M1: SEED_ENV_KEYS and seed_from_env are removed (brief D13 -- credential
# entry is fully manual).  Credentials are keyed by connection_id.
# M4: the temporary type-alias bridge (resolve("voyage")/resolve("google")
# falling through to the first connection of that type) is removed.
# All callers now use connection-id keys directly.

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

from .config import KoanConfig

log = logging.getLogger("koan.credentials")

# Path to the master key file. Mode 0600 -- readable only by the owner.
# Deliberately outside the repo (under ~/.koan/) so it is never committed.
# If lost or regenerated all stored ciphertext becomes unrecoverable.
MASTER_KEY_PATH = Path.home() / ".koan" / "master.key"

# Fernet scheme tag written into every envelope.
SCHEME = "fernet"

# Keyless local providers: default base_url per provider for availability checks.
# Intentionally empty -- lmstudio removed in M3. Retained (not deleted) as the
# keyless-local seam for a future local-provider re-add (Decision 1).
LOCAL_PROVIDERS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Key backend abstraction
# ---------------------------------------------------------------------------

class KeyBackend(Protocol):
    """Protocol for master-key sources.

    The file backend is the only implementation now. Future backends
    (OS keychain, env-master, KMS) can implement this protocol and be
    returned by get_key_backend() without touching the store or consumers.
    """

    def load_key(self) -> bytes:
        """Return a valid Fernet key (32-byte URL-safe base64-encoded bytes)."""
        ...


class FileKeyBackend:
    """File-based master key backend.

    Reads the master key from MASTER_KEY_PATH. If the file is absent,
    generates a new Fernet key, writes it with mode 0600, and returns it.
    The file is never regenerated when it already exists so existing
    ciphertext stays decryptable.
    """

    def load_key(self) -> bytes:
        """Return the Fernet key from disk, auto-generating it on first use."""
        from cryptography.fernet import Fernet
        if MASTER_KEY_PATH.exists():
            return MASTER_KEY_PATH.read_bytes().strip()
        MASTER_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        # Write with restrictive permissions: owner-read/write only.
        fd = os.open(str(MASTER_KEY_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        log.info("credentials: generated new master key at %s", MASTER_KEY_PATH)
        return key


def get_key_backend() -> KeyBackend:
    """Return the active KeyBackend instance.

    This is the single seam where future backends are selected (e.g. based
    on an env var or config flag). Swap the return value here to change the
    backend without touching the store or any consumer.
    """
    return FileKeyBackend()


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def encrypt_secret(plaintext: str, backend: KeyBackend) -> dict:
    """Encrypt a plaintext secret and return a serializable envelope dict.

    Envelope shape: {"scheme": "fernet", "ciphertext": "<token-str>"}.
    The Fernet token is self-authenticating and tamper-evident (HMAC-SHA256).
    """
    from cryptography.fernet import Fernet
    f = Fernet(backend.load_key())
    token = f.encrypt(plaintext.encode())
    return {"scheme": SCHEME, "ciphertext": token.decode()}


def decrypt_secret(envelope: dict, backend: KeyBackend) -> str:
    """Decrypt an envelope dict and return the plaintext secret.

    Raises ValueError for an unknown or malformed scheme.
    Raises cryptography.fernet.InvalidToken when the ciphertext is corrupt
    or was encrypted under a different key.
    """
    scheme = envelope.get("scheme")
    if scheme != SCHEME:
        raise ValueError(f"unknown credential scheme {scheme!r}; expected {SCHEME!r}")
    from cryptography.fernet import Fernet
    f = Fernet(backend.load_key())
    ciphertext = envelope["ciphertext"]
    return f.decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# Credential store
# ---------------------------------------------------------------------------

class CredentialStore:
    """Connection-id-keyed encrypted credential store (M1 re-key from provider-type).

    Constructed over a KoanConfig (which carries the on-disk envelopes) and a
    KeyBackend. On construction, every envelope in config.credentials is
    eagerly decrypted into an in-memory cache keyed by connection id.

    M4: the type-alias bridge (resolve("voyage")/resolve("google") falling
    through to the first connection of that type) is removed.  All callers
    now use connection-id keys directly.  Memory model selection is driven
    by MemoryBindings resolved via koan/memory/bindings.py.

    A per-envelope undecryptable entry is logged and pruned from the config --
    the store must never crash boot, and dead ciphertext must not linger. A
    systemic master-key failure leaves every envelope intact: we log and return
    with an empty cache rather than pruning all envelopes.
    """

    def __init__(self, config: KoanConfig, backend: KeyBackend) -> None:
        self._config = config
        self._backend = backend
        # In-memory cache of decrypted secrets: connection_id -> plaintext.
        self._cache: dict[str, str] = {}
        self._pruned: bool = False
        self._load_cache()

    def _load_cache(self) -> None:
        """Eagerly decrypt all envelopes from config into the cache.

        Validates the master key once up front. A systemic key failure
        (unreadable or malformed master.key) leaves every envelope intact --
        empty cache, pruned stays False -- so a bad key file can never wipe
        all stored credentials. Only a per-envelope decryption failure prunes
        that single envelope and sets pruned to True.
        """
        from cryptography.fernet import Fernet

        # Validate the master key once. If this fails, every envelope would
        # fail too, so we bail without touching any envelope -- protecting
        # against the mass-wipe data-loss path.
        try:
            Fernet(self._backend.load_key())
        except Exception as exc:
            log.error(
                "credentials: master key unavailable -- leaving all envelopes intact: %s",
                exc,
            )
            return

        # Snapshot items so the dict can be mutated during iteration.
        for key, envelope in list(self._config.credentials.items()):
            try:
                self._cache[key] = decrypt_secret(envelope, self._backend)
            except Exception as exc:
                log.warning(
                    "credentials: pruning undecryptable envelope for %r: %s",
                    key, exc,
                )
                self._config.credentials.pop(key, None)
                self._pruned = True

    def resolve(self, key: str) -> str | None:
        """Return the decrypted secret for the given connection-id key.

        Direct cache lookup by connection id only.  The M1 type-alias bridge
        (provider_type -> first connection of that type) was removed in M4.
        Callers must use the connection id as the key.
        """
        return self._cache.get(key)

    def has(self, key: str) -> bool:
        """True when a decrypted secret is available for the connection-id key.

        Direct cache lookup only -- no type-alias bridge (removed in M4).
        """
        return key in self._cache

    def set(self, key: str, secret: str) -> None:
        """Encrypt and store a secret for the given key.

        Updates both the in-memory cache and the config envelope dict.
        The caller must persist the config (save_koan_config) afterwards.
        """
        envelope = encrypt_secret(secret, self._backend)
        self._config.credentials[key] = envelope
        self._cache[key] = secret

    def remove(self, key: str) -> None:
        """Remove the credential for the given key from cache and config.

        Idempotent: no-op if the key was not stored.
        """
        self._config.credentials.pop(key, None)
        self._cache.pop(key, None)

    def available_providers(self) -> list[str]:
        """Return a sorted list of keys with a cached (decrypted) secret."""
        return sorted(self._cache)

    @property
    def pruned(self) -> bool:
        """True when one or more undecryptable envelopes were pruned at construction.

        Signals the entrypoint to persist the cleaned config. False when all
        envelopes decrypted successfully or when a systemic master-key failure
        left every envelope intact.
        """
        return self._pruned


