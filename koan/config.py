# KoanConfig dataclass and config file loader/saver.
# Storage: ~/.koan/config.yaml
#
# M1: reshaped from the legacy profile/provider_auth model to the new
# connections / configured_models / presets / active schema.  The legacy
# Profile/active_profile/provider_auth fields are surfaced as synthesized
# read-only shim properties so the web/projection/events seam keeps working
# unchanged until M5.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .types import (
    CachingPolicy,
    ConfiguredModel,
    Connection,
    MemoryBinding,
    MemoryBindings,
    Preset,
    ProviderType,
    RoleSlot,
    SlotAssignment,
    ThinkingMode,
)

log = logging.getLogger("koan.config")



@dataclass
class KoanConfig:
    """Config root for the presets/connections schema (M1; shim removed M5).

    Persists: connections (flat list of provider connection instances),
    credentials (Fernet envelopes keyed by connection id), configured_models
    (global (connection, model-id) library), memory (global memory bindings),
    scout_concurrency, presets (map of slot bundles; '$last' is the only entry
    today), active (always '$last' today).

    Credentials are keyed by connection id; secrets are Fernet ciphertext and
    never appear in plaintext.  The old profile/active_profile/provider_auth
    shim properties were removed in M5 (brief D8, plan-milestone-5.md).
    """

    connections: list[Connection] = field(default_factory=list)
    # On-disk credential envelopes (Fernet ciphertext); keyed by connection id.
    # Decrypted by CredentialStore; secrets never appear in plaintext here.
    credentials: dict[str, dict] = field(default_factory=dict)
    configured_models: list[ConfiguredModel] = field(default_factory=list)
    memory: MemoryBindings | None = None
    scout_concurrency: int = 8
    max_retry_attempts: int = 10
    max_retry_wait_seconds: float = 60.0
    # Preset map: '$'-prefixed keys are reserved for the system (brief D7).
    presets: dict[str, Preset] = field(default_factory=dict)
    active: str = "$last"


# -- Write lock (lazily initialized) ------------------------------------------

_config_write_lock: asyncio.Lock | None = None


def _get_write_lock() -> asyncio.Lock:
    global _config_write_lock
    if _config_write_lock is None:
        _config_write_lock = asyncio.Lock()
    return _config_write_lock


# -- Parsers ------------------------------------------------------------------


def _parse_caching_policy(raw: object) -> CachingPolicy:
    """Parse a CachingPolicy from a config sub-dict.

    Reads only 'mode' (auto/off); any legacy 'ttl' key is silently ignored
    (backward-compatible: old configs still parse cleanly, and the stale
    key is dropped the next time the config is serialized).  Falls back to
    the default CachingPolicy() for any missing or non-dict value.
    """
    if not isinstance(raw, dict):
        return CachingPolicy()
    return CachingPolicy(mode=raw.get("mode", "auto"))


def _parse_connections(raw: object) -> list[Connection]:
    """Parse a list of Connection from the snake_case config.

    Each entry requires 'id' and 'type'; all other fields are optional.
    Malformed or missing-required-field entries are skipped with a warning.
    """
    if not isinstance(raw, list):
        return []
    results: list[Connection] = []
    for entry in raw:
        if not isinstance(entry, dict):
            log.warning("connections entry is not an object; skipping.")
            continue
        conn_id = entry.get("id", "")
        conn_type = entry.get("type", "")
        if not conn_id or not conn_type:
            log.warning("connections entry missing id or type; skipping.")
            continue
        results.append(Connection(
            id=conn_id,
            type=conn_type,
            base_url=entry.get("base_url") or None,
            region=entry.get("region") or None,
            azure_deployment=entry.get("azure_deployment") or None,
            api_version=entry.get("api_version") or None,
            timeout=float(entry["timeout"]) if entry.get("timeout") is not None else None,
        ))
    return results


def _parse_configured_models(raw: object) -> list[ConfiguredModel]:
    """Parse a list of ConfiguredModel from the snake_case config.

    Each entry requires 'id', 'connection_id', and 'model_id'.
    Optional 'embedding_dim' (integer) is preserved as-is; absent or null
    values become None (use the voyage model default from the catalog).
    """
    if not isinstance(raw, list):
        return []
    results: list[ConfiguredModel] = []
    for entry in raw:
        if not isinstance(entry, dict):
            log.warning("configured_models entry is not an object; skipping.")
            continue
        cm_id = entry.get("id", "")
        conn_id = entry.get("connection_id", "")
        model_id = entry.get("model_id", "")
        if not cm_id or not conn_id or not model_id:
            log.warning("configured_models entry missing id/connection_id/model_id; skipping.")
            continue
        results.append(ConfiguredModel(
            id=cm_id,
            connection_id=conn_id,
            model_id=model_id,
            resolved_from=entry.get("resolved_from") or None,
            embedding_dim=int(entry["embedding_dim"]) if entry.get("embedding_dim") is not None else None,
        ))
    return results


def _parse_slot_assignment(raw: object) -> SlotAssignment | None:
    """Parse a SlotAssignment from a config dict; returns None on malformed input."""
    if not isinstance(raw, dict):
        return None
    cm_id = raw.get("configured_model_id", "")
    if not cm_id:
        return None
    return SlotAssignment(
        configured_model_id=cm_id,
        thinking=raw.get("thinking", "disabled"),
        caching=_parse_caching_policy(raw.get("caching")),
    )


def _parse_presets(raw: object) -> dict[str, Preset]:
    """Parse the presets map from the snake_case config.

    Each key is a preset name; '$'-prefixed keys are reserved for the system.
    Malformed slot entries are skipped.
    """
    if not isinstance(raw, dict):
        return {}
    results: dict[str, Preset] = {}
    for preset_name, preset_raw in raw.items():
        if not isinstance(preset_raw, dict):
            log.warning("presets[%r] is not an object; skipping.", preset_name)
            continue
        slots_raw = preset_raw.get("slots", {})
        if not isinstance(slots_raw, dict):
            log.warning("presets[%r].slots is not an object; skipping.", preset_name)
            continue
        slots: dict[RoleSlot, SlotAssignment] = {}
        for slot_name, slot_raw in slots_raw.items():
            assignment = _parse_slot_assignment(slot_raw)
            if assignment is None:
                log.warning(
                    "presets[%r].slots[%r] malformed; skipping slot.",
                    preset_name, slot_name,
                )
                continue
            slots[slot_name] = assignment
        results[preset_name] = Preset(slots=slots)
    return results


def _parse_memory_binding(raw: object) -> MemoryBinding | None:
    """Parse a MemoryBinding from a config dict; returns None on malformed input.

    Stale 'thinking' keys in YAML are silently ignored (hard cutover).
    """
    if not isinstance(raw, dict):
        return None
    cm_id = raw.get("configured_model_id", "")
    if not cm_id:
        return None
    return MemoryBinding(
        configured_model_id=cm_id,
        caching=_parse_caching_policy(raw.get("caching")),
    )


def _parse_memory(raw: object) -> MemoryBindings | None:
    """Parse the global MemoryBindings from the config; returns None when absent.

    Stale 'memory_llm' and 'reflect_llm' keys in YAML are silently ignored.
    """
    if not isinstance(raw, dict):
        return None
    return MemoryBindings(
        embedding=_parse_memory_binding(raw.get("embedding")),
    )


def _parse_credentials(raw: object) -> dict[str, dict]:
    """Parse the on-disk credentials envelope dict from the parsed config.

    Accepts only well-formed entries: each value must be a dict with at least
    'scheme' and 'ciphertext' keys.  Malformed entries are silently dropped so
    a partially-corrupt config.yaml does not crash boot.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for key, envelope in raw.items():
        if (
            isinstance(envelope, dict)
            and isinstance(envelope.get("scheme"), str)
            and isinstance(envelope.get("ciphertext"), str)
        ):
            out[key] = envelope
        else:
            log.warning("credentials: dropping malformed envelope for key %r", key)
    return out


def _parse_scout_concurrency(raw: dict) -> int:
    """Read scout_concurrency from the parsed config dict; default 8 on missing or invalid input."""
    if not isinstance(raw, dict):
        return 8
    sc = raw.get("scout_concurrency")
    if isinstance(sc, bool):
        return 8
    if isinstance(sc, int) and sc > 0:
        return sc
    return 8


def _parse_max_retry_attempts(raw: dict) -> int:
    """Read max_retry_attempts from the parsed config dict; default 10 on missing or invalid input."""
    if not isinstance(raw, dict):
        return 10
    v = raw.get("max_retry_attempts")
    if isinstance(v, bool):
        return 10
    if isinstance(v, int) and v > 0:
        return v
    return 10


def _parse_max_retry_wait_seconds(raw: dict) -> float:
    """Read max_retry_wait_seconds from the parsed config dict; default 60.0 on missing or invalid input."""
    if not isinstance(raw, dict):
        return 60.0
    v = raw.get("max_retry_wait_seconds")
    if isinstance(v, bool):
        return 60.0
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    return 60.0


# -- Loaders / savers ---------------------------------------------------------

async def load_koan_config(home: Path) -> KoanConfig:
    """Load KoanConfig from the given koan home directory.

    Derives the config path as home / "config.yaml".  Reads the
    connections/configured_models/presets/active/memory schema from snake_case
    YAML.  Returns a default (empty) config on a missing or invalid file.  The
    credentials field carries opaque Fernet envelopes keyed by connection id;
    decryption happens in CredentialStore (koan/credentials.py).
    """
    config_path = home / "config.yaml"
    defaults = KoanConfig()

    try:
        text = config_path.read_text("utf-8")
    except FileNotFoundError:
        return defaults

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        log.warning("config.yaml is not valid YAML; treating config as absent.")
        return defaults

    # yaml.safe_load("") returns None; treat as absent
    if not isinstance(parsed, dict):
        log.warning("config.yaml top-level value is not an object; treating config as absent.")
        return defaults

    active = parsed.get("active", "$last")
    if not isinstance(active, str) or not active:
        active = "$last"

    return KoanConfig(
        connections=_parse_connections(parsed.get("connections", [])),
        credentials=_parse_credentials(parsed.get("credentials")),
        configured_models=_parse_configured_models(parsed.get("configured_models", [])),
        memory=_parse_memory(parsed.get("memory")),
        scout_concurrency=_parse_scout_concurrency(parsed),
        max_retry_attempts=_parse_max_retry_attempts(parsed),
        max_retry_wait_seconds=_parse_max_retry_wait_seconds(parsed),
        presets=_parse_presets(parsed.get("presets", {})),
        active=active,
    )


def _serialize_slot_assignment(slot: SlotAssignment) -> dict:
    """Serialize a SlotAssignment to a snake_case dict for YAML output.

    The 'caching' block carries only 'mode'; cache duration (tier) is
    code-derived from the agent role and is no longer stored in config.
    """
    return {
        "configured_model_id": slot.configured_model_id,
        "thinking": slot.thinking,
        "caching": {"mode": slot.caching.mode},
    }


def _config_to_dict(config: "KoanConfig") -> dict:
    """Serialize a KoanConfig to a snake_case dict suitable for YAML output.

    Pure function: produces the dict without any I/O side-effects.
    Credential envelopes are opaque Fernet ciphertext -- plaintext secrets
    are never included.  Used by both save_koan_config (global config) and
    write_run_config (per-run frozen snapshot).
    """
    data: dict = {}

    data["connections"] = [
        {
            "id": c.id,
            "type": c.type,
            **({"base_url": c.base_url} if c.base_url else {}),
            **({"region": c.region} if c.region else {}),
            **({"azure_deployment": c.azure_deployment} if c.azure_deployment else {}),
            **({"api_version": c.api_version} if c.api_version else {}),
            **({"timeout": c.timeout} if c.timeout is not None else {}),
        }
        for c in config.connections
    ]

    # Credential envelopes are opaque Fernet ciphertext; no plaintext
    # secret is ever written here.
    data["credentials"] = config.credentials

    data["configured_models"] = [
        {
            "id": cm.id,
            "connection_id": cm.connection_id,
            "model_id": cm.model_id,
            **({"resolved_from": cm.resolved_from} if cm.resolved_from else {}),
            # Omit when None: an absent embedding_dim means "use model default".
            **({"embedding_dim": cm.embedding_dim} if cm.embedding_dim is not None else {}),
        }
        for cm in config.configured_models
    ]

    if config.memory is not None:
        mem: dict = {}
        for binding_name in ("embedding",):
            binding = getattr(config.memory, binding_name)
            if binding is not None:
                entry: dict = {"configured_model_id": binding.configured_model_id}
                # 'caching' carries only 'mode'.
                entry["caching"] = {"mode": binding.caching.mode}
                mem[binding_name] = entry
        if mem:
            data["memory"] = mem

    data["scout_concurrency"] = config.scout_concurrency
    data["max_retry_attempts"] = config.max_retry_attempts
    data["max_retry_wait_seconds"] = config.max_retry_wait_seconds

    data["presets"] = {
        preset_name: {
            "slots": {
                slot_name: _serialize_slot_assignment(slot)
                for slot_name, slot in preset.slots.items()
            }
        }
        for preset_name, preset in config.presets.items()
    }

    # Omit active when it is the default to keep hand-edited files minimal.
    if config.active != "$last":
        data["active"] = config.active

    return data


async def write_run_config(config: "KoanConfig", run_dir: "str | Path") -> None:
    """Serialize the frozen per-run config to <run_dir>/run-config.yaml.

    Written once at /api/start-run time as the durable, auditable record of
    exactly which connections/models/credentials the run used.  Carries the
    same opaque Fernet ciphertext envelopes as config.yaml -- plaintext
    secrets are never written.  Not protected by the global write lock because
    this file is run-scoped and written only once per run.
    """
    import os
    data = _config_to_dict(config)
    # width=4096 prevents line-folding of long ciphertext values.
    text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=4096)
    dest = Path(run_dir) / "run-config.yaml"
    tmp = dest.with_suffix(".yaml.tmp")
    tmp.write_text(text, "utf-8")
    os.replace(str(tmp), str(dest))


async def save_koan_config(config: KoanConfig, home: Path) -> None:
    """Write KoanConfig to home/config.yaml atomically via a tmp-file rename.

    Derives the config path as home / "config.yaml".  Pure fresh dump from
    the in-memory KoanConfig -- no read-modify-write.  Serializes the new
    schema: connections, credentials (opaque Fernet ciphertext; plaintext
    secrets are never written), configured_models, memory, scout_concurrency,
    presets, and active.  The temp file lands in the same directory so the
    rename is within-filesystem (atomic).
    """
    async with _get_write_lock():
        config_dir = home
        config_dir.mkdir(parents=True, exist_ok=True)

        config_path = home / "config.yaml"
        data = _config_to_dict(config)

        # width=4096 prevents line-folding of long ciphertext values.
        text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False,
                              allow_unicode=True, width=4096)
        tmp_path = config_path.with_suffix(".yaml.tmp")
        tmp_path.write_text(text, "utf-8")
        tmp_path.rename(config_path)
