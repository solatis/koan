# Unit tests for M1 config schema and adapter: new round-trip, ModelSpec
# resolution via slot/preset/connection, compute_builtin_profiles returning {},
# and resolve_provider_auth with the new Connection-based signature.

from __future__ import annotations

import asyncio

import pytest

from koan.agents.registry import AgentRegistry
from koan.config import KoanConfig, load_koan_config, save_koan_config
from koan.credentials import CredentialStore, FileKeyBackend
from koan.types import (
    CachingPolicy,
    ConfiguredModel,
    Connection,
    ModelSpec,
    MemoryBinding,
    MemoryBindings,
    Preset,
    SlotAssignment,
)


# -- helpers ------------------------------------------------------------------

def _make_minimal_config(
    conn_id: str = "google-direct",
    conn_type: str = "google",
    cm_id: str = "gemini-pro-cm",
    model_id: str = "gemini-3.1-pro-preview",
) -> KoanConfig:
    """Build a minimal KoanConfig with one connection, one model, and a $last preset."""
    conn = Connection(id=conn_id, type=conn_type)
    cm = ConfiguredModel(id=cm_id, connection_id=conn_id, model_id=model_id)
    slot = SlotAssignment(configured_model_id=cm_id, thinking="high")
    preset = Preset(slots={"strong": slot, "standard": slot, "cheap": slot})
    return KoanConfig(
        connections=[conn],
        configured_models=[cm],
        presets={"$last": preset},
        active="$last",
    )


def _make_credential_store(config: KoanConfig, tmp_path, monkeypatch) -> CredentialStore:
    """Build a CredentialStore with a tmp master key."""
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", tmp_path / "master.key")
    return CredentialStore(config, FileKeyBackend())


# -- resolve_model_spec -------------------------------------------------------

class TestResolveModelSpec:
    def test_orchestrator_resolves_strong_slot(self, tmp_path, monkeypatch):
        """Orchestrator maps to 'strong' slot and returns a ModelSpec with connection_id."""
        config = _make_minimal_config()
        reg = AgentRegistry()
        spec = reg.resolve_model_spec("orchestrator", config)
        assert spec.provider == "google"
        assert spec.model == "gemini-3.1-pro-preview"
        assert spec.thinking == "high"
        assert spec.connection_id == "google-direct"

    def test_executor_resolves_standard_slot(self, tmp_path, monkeypatch):
        """Executor maps to 'standard' slot."""
        config = _make_minimal_config()
        reg = AgentRegistry()
        spec = reg.resolve_model_spec("executor", config)
        assert spec.connection_id == "google-direct"

    def test_scout_resolves_cheap_slot(self, tmp_path, monkeypatch):
        """Scout maps to 'cheap' slot."""
        config = _make_minimal_config()
        reg = AgentRegistry()
        spec = reg.resolve_model_spec("scout", config)
        assert spec.connection_id == "google-direct"
        assert spec.thinking == "high"

    def test_missing_preset_raises_unconfigured(self):
        """Missing active preset raises AgentError with code 'unconfigured'."""
        from koan.agents.base import AgentError
        config = KoanConfig()  # no presets
        reg = AgentRegistry()
        with pytest.raises(AgentError) as exc:
            reg.resolve_model_spec("orchestrator", config)
        assert exc.value.diagnostic.code == "unconfigured"

    def test_missing_slot_raises_unconfigured(self):
        """Preset with no 'strong' slot raises AgentError with code 'unconfigured'."""
        from koan.agents.base import AgentError
        conn = Connection(id="g", type="google")
        cm = ConfiguredModel(id="m", connection_id="g", model_id="flash")
        # Only cheap slot assigned; orchestrator needs strong.
        preset = Preset(slots={"cheap": SlotAssignment(configured_model_id="m", thinking="disabled")})
        config = KoanConfig(
            connections=[conn],
            configured_models=[cm],
            presets={"$last": preset},
        )
        reg = AgentRegistry()
        with pytest.raises(AgentError) as exc:
            reg.resolve_model_spec("orchestrator", config)
        assert exc.value.diagnostic.code == "unconfigured"

    def test_missing_configured_model_raises_unconfigured(self):
        """Slot pointing to a non-existent configured_model_id raises unconfigured."""
        from koan.agents.base import AgentError
        conn = Connection(id="g", type="google")
        slot = SlotAssignment(configured_model_id="nonexistent-cm", thinking="high")
        preset = Preset(slots={"strong": slot})
        config = KoanConfig(
            connections=[conn],
            configured_models=[],  # no matching model
            presets={"$last": preset},
        )
        reg = AgentRegistry()
        with pytest.raises(AgentError) as exc:
            reg.resolve_model_spec("orchestrator", config)
        assert exc.value.diagnostic.code == "unconfigured"

    def test_missing_connection_raises_unconfigured(self):
        """ConfiguredModel pointing to a non-existent connection raises unconfigured."""
        from koan.agents.base import AgentError
        cm = ConfiguredModel(id="m", connection_id="nonexistent-conn", model_id="flash")
        slot = SlotAssignment(configured_model_id="m", thinking="high")
        preset = Preset(slots={"strong": slot})
        config = KoanConfig(
            connections=[],  # no matching connection
            configured_models=[cm],
            presets={"$last": preset},
        )
        reg = AgentRegistry()
        with pytest.raises(AgentError) as exc:
            reg.resolve_model_spec("orchestrator", config)
        assert exc.value.diagnostic.code == "unconfigured"

    def test_context_window_set_from_catalog(self):
        """ModelSpec.context_window is populated from context_window_for."""
        config = _make_minimal_config(
            model_id="gemini-3.1-pro-preview",
        )
        reg = AgentRegistry()
        spec = reg.resolve_model_spec("orchestrator", config)
        # gemini-3.1-pro-preview is in MODEL_CAPABILITIES with a 1_000_000 fallback.
        assert spec.context_window == 1_000_000


# compute_builtin_profiles tests removed in M5: function deleted (plan-milestone-5.md).

# -- Config round-trip (new schema) -------------------------------------------

class TestConfigRoundTrip:
    @pytest.mark.anyio
    async def test_new_schema_round_trip(self, tmp_path, monkeypatch):
        """KoanConfig with new schema round-trips through save/load correctly."""
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)

        conn = Connection(
            id="anthropic-direct",
            type="anthropic",
            region="us-east-1",
            base_url="https://example.test",
        )
        cm = ConfiguredModel(
            id="opus-cm",
            connection_id="anthropic-direct",
            model_id="claude-opus-4-0",
            resolved_from="newest(claude-opus)@2026-06-08 -> claude-opus-4-0",
        )
        slot = SlotAssignment(
            configured_model_id="opus-cm",
            thinking="high",
            caching=CachingPolicy(mode="auto", ttl="5m"),
        )
        preset = Preset(slots={"strong": slot})
        original = KoanConfig(
            connections=[conn],
            configured_models=[cm],
            presets={"$last": preset},
            active="$last",
            scout_concurrency=4,
        )

        await save_koan_config(original)
        loaded = await load_koan_config()

        assert loaded.active == "$last"
        assert loaded.scout_concurrency == 4
        assert len(loaded.connections) == 1
        c = loaded.connections[0]
        assert c.id == "anthropic-direct"
        assert c.type == "anthropic"
        assert c.region == "us-east-1"
        assert c.base_url == "https://example.test"

        assert len(loaded.configured_models) == 1
        m = loaded.configured_models[0]
        assert m.id == "opus-cm"
        assert m.connection_id == "anthropic-direct"
        assert m.model_id == "claude-opus-4-0"
        assert m.resolved_from is not None

        assert "$last" in loaded.presets
        p = loaded.presets["$last"]
        assert "strong" in p.slots
        s = p.slots["strong"]
        assert s.configured_model_id == "opus-cm"
        assert s.thinking == "high"

    @pytest.mark.anyio
    async def test_memory_bindings_round_trip(self, tmp_path, monkeypatch):
        """MemoryBindings persists and loads correctly."""
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)

        original = KoanConfig(
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="voyage-cm"),
                memory_llm=MemoryBinding(configured_model_id="gemini-flash-cm"),
                reflect_llm=MemoryBinding(configured_model_id="gemini-pro-cm"),
            ),
        )
        await save_koan_config(original)
        loaded = await load_koan_config()

        assert loaded.memory is not None
        assert loaded.memory.embedding.configured_model_id == "voyage-cm"
        assert loaded.memory.memory_llm.configured_model_id == "gemini-flash-cm"
        assert loaded.memory.reflect_llm.configured_model_id == "gemini-pro-cm"


# TestShimProperties removed in M5: profiles/active_profile shim deleted from KoanConfig.

# -- resolve_provider_auth (new signature) ------------------------------------

class TestResolveProviderAuth:
    """Tests for the Connection-based resolve_provider_auth."""

    def _make_store(self, conn: Connection, secret: str, tmp_path, monkeypatch) -> CredentialStore:
        """Build a store with one connection id's secret stored."""
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", tmp_path / "master.key")
        config = KoanConfig(connections=[conn])
        store = CredentialStore(config, FileKeyBackend())
        store.set(conn.id, secret)
        return store

    def test_resolves_api_key_and_region_from_connection(self, tmp_path, monkeypatch):
        """resolve_provider_auth returns api_key from store and region/base_url from Connection."""
        from koan.agents.adapter import ResolvedProviderAuth, resolve_provider_auth

        conn = Connection(
            id="bedrock-direct",
            type="bedrock",
            region="us-east-1",
            base_url="https://ep",
        )
        store = self._make_store(conn, "tok", tmp_path, monkeypatch)
        result = resolve_provider_auth(conn, store)
        assert isinstance(result, ResolvedProviderAuth)
        assert result.api_key == "tok"
        assert result.region == "us-east-1"
        assert result.base_url == "https://ep"

    def test_none_store_returns_none_api_key(self):
        """resolve_provider_auth returns api_key=None when store is None (no crash)."""
        from koan.agents.adapter import resolve_provider_auth

        conn = Connection(id="anthropic-direct", type="anthropic")
        result = resolve_provider_auth(conn, None)
        assert result.api_key is None
        assert result.region is None
        assert result.base_url is None

    def test_connection_with_no_region_or_base_url(self, tmp_path, monkeypatch):
        """Connection without region/base_url resolves Nones for those fields."""
        from koan.agents.adapter import resolve_provider_auth

        conn = Connection(id="openai-direct", type="openai")
        store = self._make_store(conn, "sk-test", tmp_path, monkeypatch)
        result = resolve_provider_auth(conn, store)
        assert result.api_key == "sk-test"
        assert result.region is None
        assert result.base_url is None


# -- Credential store round-trip (via config) ----------------------------------

class TestCredentialConfigRoundTrip:
    @pytest.mark.anyio
    async def test_credentials_envelope_round_trips(self, tmp_path, monkeypatch):
        """A credentials envelope written to config.yaml is loaded back correctly."""
        config_path = tmp_path / "config.yaml"
        key_path = tmp_path / "master.key"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)
        monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)

        backend = FileKeyBackend()
        config = KoanConfig()
        store = CredentialStore(config, backend)
        store.set("google-direct", "round-trip-key")

        await save_koan_config(config)
        loaded = await load_koan_config()

        store2 = CredentialStore(loaded, backend)
        assert store2.resolve("google-direct") == "round-trip-key"


# ---------------------------------------------------------------------------
# embedding_dim round-trip
# ---------------------------------------------------------------------------

class TestEmbeddingDimRoundTrip:
    @pytest.mark.anyio
    async def test_embedding_dim_persists_and_loads(self, tmp_path, monkeypatch):
        """ConfiguredModel.embedding_dim round-trips through save/load."""
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)

        original = KoanConfig(
            connections=[Connection(id="voyage-1", type="voyage")],
            configured_models=[
                ConfiguredModel(
                    id="voyage-embed",
                    connection_id="voyage-1",
                    model_id="voyage-4-large",
                    embedding_dim=512,
                )
            ],
        )
        await save_koan_config(original)
        loaded = await load_koan_config()

        assert len(loaded.configured_models) == 1
        cm = loaded.configured_models[0]
        assert cm.embedding_dim == 512

    @pytest.mark.anyio
    async def test_embedding_dim_none_omitted_from_yaml(self, tmp_path, monkeypatch):
        """embedding_dim=None is not written to YAML (omit-when-None convention)."""
        import yaml
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr("koan.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("koan.config._config_write_lock", None)

        original = KoanConfig(
            connections=[Connection(id="voyage-1", type="voyage")],
            configured_models=[
                ConfiguredModel(
                    id="voyage-embed",
                    connection_id="voyage-1",
                    model_id="voyage-4-large",
                    embedding_dim=None,
                )
            ],
        )
        await save_koan_config(original)
        parsed = yaml.safe_load(config_path.read_text())
        assert "embedding_dim" not in parsed["configured_models"][0]


# ---------------------------------------------------------------------------
# _effective_embedding_identity
# ---------------------------------------------------------------------------

class TestEffectiveEmbeddingIdentity:
    """Pure-data tests for _effective_embedding_identity (web/app.py helper)."""

    @staticmethod
    def _cfg(
        *,
        conn_type: str = "voyage",
        model_id: str = "voyage-4-large",
        embedding_dim: int | None = None,
    ) -> KoanConfig:
        """Build a minimal KoanConfig wired up for the embedding binding."""
        return KoanConfig(
            connections=[Connection(id="v1", type=conn_type)],
            configured_models=[
                ConfiguredModel(
                    id="em",
                    connection_id="v1",
                    model_id=model_id,
                    embedding_dim=embedding_dim,
                )
            ],
            memory=MemoryBindings(
                embedding=MemoryBinding(configured_model_id="em"),
            ),
        )

    def test_returns_model_and_resolved_dim(self):
        from koan.web.app import _effective_embedding_identity
        cfg = self._cfg(embedding_dim=None)
        identity = _effective_embedding_identity(cfg)
        assert identity == ("voyage-4-large", 1024)  # catalog default

    def test_returns_explicit_dim(self):
        from koan.web.app import _effective_embedding_identity
        cfg = self._cfg(embedding_dim=512)
        identity = _effective_embedding_identity(cfg)
        assert identity == ("voyage-4-large", 512)

    def test_non_voyage_connection_returns_none(self):
        from koan.web.app import _effective_embedding_identity
        cfg = self._cfg(conn_type="anthropic")
        assert _effective_embedding_identity(cfg) is None

    def test_unrecognized_model_returns_none(self):
        from koan.web.app import _effective_embedding_identity
        cfg = self._cfg(model_id="voyage-unknown")
        assert _effective_embedding_identity(cfg) is None

    def test_no_memory_returns_none(self):
        from koan.web.app import _effective_embedding_identity
        cfg = KoanConfig(
            connections=[Connection(id="v1", type="voyage")],
            configured_models=[
                ConfiguredModel(id="em", connection_id="v1", model_id="voyage-4-large")
            ],
            memory=None,
        )
        assert _effective_embedding_identity(cfg) is None
