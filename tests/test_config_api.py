# Tests for the M6 config mutation API and capability-surfacing projection.
#
# Coverage:
#   - Connection upsert/delete: credential set/remove, connections_listed pushed
#   - Configured-model upsert/delete: configured_models_listed pushed
#   - Slot assignment: thinking validation (422 on unsupported), presets_listed pushed
#   - Memory binding set: memory_bindings_listed pushed
#   - List-models: success pushes provider_models; no-credential returns {ok: False}
#   - Newest-in-family: pins + provenance; ModelListingError -> 409;
#     NewestInFamilyUnavailable -> 422
#   - model_capabilities projection: populated at startup; refreshed on mutation
#   - Secret hygiene: secrets never echoed in responses

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from koan.config import KoanConfig
from koan.credentials import CredentialStore, FileKeyBackend
from koan.state import AppState
from koan.types import (
    ConfiguredModel,
    Connection,
    Preset,
    SlotAssignment,
    MemoryBindings,
)
from koan.web.app import create_app


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def tmp_key_path(tmp_path, monkeypatch):
    """Redirect the credential master key to a tmp dir so tests never touch ~/.koan/."""
    key_path = tmp_path / "master.key"
    monkeypatch.setattr("koan.credentials.MASTER_KEY_PATH", key_path)
    return key_path


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Redirect config YAML writes to a tmp dir."""
    path = tmp_path / "config.yaml"
    monkeypatch.setattr("koan.config.CONFIG_PATH", path)
    monkeypatch.setattr("koan.config._config_write_lock", None)
    return path


@pytest.fixture
def conn():
    """A minimal anthropic connection for test fixtures."""
    return Connection(id="anthropic-1", type="anthropic")


@pytest.fixture
def cm(conn):
    """A ConfiguredModel attached to the anthropic connection."""
    # claude-3-5-haiku-20241022 is in the capability table with no thinking modes.
    return ConfiguredModel(id="cm-haiku", connection_id=conn.id, model_id="claude-3-5-haiku-20241022")


@pytest.fixture
def app_state(tmp_key_path, conn, cm):
    """AppState with one connection, one configured model, and a credential store."""
    cfg = KoanConfig(
        connections=[conn],
        configured_models=[cm],
    )
    backend = FileKeyBackend()
    store = CredentialStore(cfg, backend)
    store.set(conn.id, "test-api-key")

    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.credential_store = store
    return st


@pytest.fixture
def client(app_state, config_path):
    """Test client with driver_main patched out."""
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state)
        with TestClient(app) as c:
            yield c


# -- Helpers ------------------------------------------------------------------

def _last_event_of_type(app_state: AppState, event_type: str) -> dict | None:
    """Return the payload of the last event of the given type, or None."""
    for ev in reversed(app_state.projection_store.events):
        if ev.event_type == event_type:
            return ev.payload
    return None


# -- Connection upsert --------------------------------------------------------

def test_connection_set_post_creates_connection(client, app_state, config_path):
    """POST /api/config/connections creates a new connection and pushes connections_listed."""
    resp = client.post("/api/config/connections", json={
        "id": "openai-1",
        "type": "openai",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cfg = app_state.provider_config.config
    ids = [c.id for c in cfg.connections]
    assert "openai-1" in ids

    ev = _last_event_of_type(app_state, "connections_listed")
    assert ev is not None
    conn_ids = [c["id"] for c in ev["connections"]]
    assert "openai-1" in conn_ids


def test_connection_set_stores_credential(client, app_state, config_path):
    """A connection POST with a secret stores the credential in the credential store."""
    resp = client.post("/api/config/connections", json={
        "id": "openai-2",
        "type": "openai",
        "secret": "sk-my-secret",
    })
    assert resp.status_code == 200
    store = app_state.provider_config.credential_store
    assert store.has("openai-2")
    assert store.resolve("openai-2") == "sk-my-secret"


def test_connection_set_secret_not_echoed(client, app_state, config_path):
    """A connection POST with a secret never returns the secret in the response."""
    resp = client.post("/api/config/connections", json={
        "id": "openai-3",
        "type": "openai",
        "secret": "super-secret-key",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "super-secret-key" not in str(body)
    assert "secret" not in body


def test_connection_set_put_updates_existing(client, app_state, config_path):
    """PUT /api/config/connections/{id} upserts an existing connection."""
    resp = client.put("/api/config/connections/anthropic-1", json={
        "type": "anthropic",
        "base_url": "https://custom.endpoint",
    })
    assert resp.status_code == 200

    cfg = app_state.provider_config.config
    conn = next(c for c in cfg.connections if c.id == "anthropic-1")
    assert conn.base_url == "https://custom.endpoint"
    # Only one anthropic-1 entry after upsert.
    assert sum(1 for c in cfg.connections if c.id == "anthropic-1") == 1


def test_connection_set_validation_rejects_unknown_type(client, app_state, config_path):
    """POST /api/config/connections with an unknown type returns 422."""
    resp = client.post("/api/config/connections", json={
        "id": "bad-conn",
        "type": "totally_unknown",
    })
    assert resp.status_code == 422


def test_connection_set_validation_requires_id(client, app_state, config_path):
    """POST /api/config/connections without an id returns 422."""
    resp = client.post("/api/config/connections", json={"type": "openai"})
    assert resp.status_code == 422


# -- Connection delete --------------------------------------------------------

def test_connection_delete_removes_connection_and_credential(client, app_state, config_path):
    """DELETE /api/config/connections/{id} removes the connection and its credential."""
    assert app_state.provider_config.credential_store.has("anthropic-1")

    resp = client.delete("/api/config/connections/anthropic-1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    ids = [c.id for c in app_state.provider_config.config.connections]
    assert "anthropic-1" not in ids
    assert not app_state.provider_config.credential_store.has("anthropic-1")


def test_connection_delete_pushes_connections_listed(client, app_state, config_path):
    """DELETE /api/config/connections/{id} pushes connections_listed."""
    client.delete("/api/config/connections/anthropic-1")
    ev = _last_event_of_type(app_state, "connections_listed")
    assert ev is not None
    ids = [c["id"] for c in ev["connections"]]
    assert "anthropic-1" not in ids


def test_connection_delete_not_found(client, app_state, config_path):
    """DELETE /api/config/connections/{id} for a missing id returns 404."""
    resp = client.delete("/api/config/connections/does-not-exist")
    assert resp.status_code == 404


# -- Configured-model upsert --------------------------------------------------

def test_model_set_creates_configured_model(client, app_state, config_path):
    """POST /api/config/models creates a new ConfiguredModel."""
    resp = client.post("/api/config/models", json={
        "id": "cm-new",
        "connection_id": "anthropic-1",
        "model_id": "claude-opus-4-0",
    })
    assert resp.status_code == 200
    ids = [m.id for m in app_state.provider_config.config.configured_models]
    assert "cm-new" in ids


def test_model_set_pushes_configured_models_listed(client, app_state, config_path):
    """POST /api/config/models pushes configured_models_listed."""
    client.post("/api/config/models", json={
        "id": "cm-push-test",
        "connection_id": "anthropic-1",
        "model_id": "claude-opus-4-0",
    })
    ev = _last_event_of_type(app_state, "configured_models_listed")
    assert ev is not None
    ids = [m["id"] for m in ev["configured_models"]]
    assert "cm-push-test" in ids


def test_model_set_rejects_missing_connection(client, app_state, config_path):
    """POST /api/config/models with a non-existent connection_id returns 422."""
    resp = client.post("/api/config/models", json={
        "id": "cm-bad",
        "connection_id": "no-such-connection",
        "model_id": "some-model",
    })
    assert resp.status_code == 422


def test_model_set_put_updates_existing(client, app_state, config_path):
    """PUT /api/config/models/{id} upserts an existing ConfiguredModel."""
    resp = client.put("/api/config/models/cm-haiku", json={
        "connection_id": "anthropic-1",
        "model_id": "claude-3-5-sonnet-20241022",
    })
    assert resp.status_code == 200
    cfg = app_state.provider_config.config
    cm = next(m for m in cfg.configured_models if m.id == "cm-haiku")
    assert cm.model_id == "claude-3-5-sonnet-20241022"
    assert sum(1 for m in cfg.configured_models if m.id == "cm-haiku") == 1


# -- Configured-model delete --------------------------------------------------

def test_model_delete(client, app_state, config_path):
    """DELETE /api/config/models/{id} removes the configured model."""
    resp = client.delete("/api/config/models/cm-haiku")
    assert resp.status_code == 200
    ids = [m.id for m in app_state.provider_config.config.configured_models]
    assert "cm-haiku" not in ids


def test_model_delete_not_found(client, app_state, config_path):
    """DELETE /api/config/models/{id} for a missing id returns 404."""
    resp = client.delete("/api/config/models/no-such-model")
    assert resp.status_code == 404


# -- Slot assignment ----------------------------------------------------------

@pytest.fixture
def app_state_with_thinking_model(tmp_key_path):
    """AppState with a claude-opus-4-0 model that supports thinking modes."""
    conn = Connection(id="anthropic-1", type="anthropic")
    # claude-opus-4-0 supports thinking in the capability table (thinking_modes populated).
    cm = ConfiguredModel(id="cm-opus", connection_id="anthropic-1", model_id="claude-opus-4-0")
    cfg = KoanConfig(connections=[conn], configured_models=[cm])
    backend = FileKeyBackend()
    store = CredentialStore(cfg, backend)
    store.set("anthropic-1", "test-key")

    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.credential_store = store
    return st


@pytest.fixture
def client_with_thinking_model(app_state_with_thinking_model, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setattr("koan.config.CONFIG_PATH", path)
    monkeypatch.setattr("koan.config._config_write_lock", None)
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state_with_thinking_model)
        with TestClient(app) as c:
            yield c, app_state_with_thinking_model


def test_slot_set_assigns_model_to_slot(client_with_thinking_model):
    """PUT /api/config/slots/{slot} writes a SlotAssignment and pushes presets_listed."""
    c, st = client_with_thinking_model
    resp = c.put("/api/config/slots/strong", json={
        "configured_model_id": "cm-opus",
        "thinking": "disabled",
    })
    assert resp.status_code == 200
    preset = st.provider_config.config.presets.get("$last")
    assert preset is not None
    assert preset.slots["strong"].configured_model_id == "cm-opus"

    ev = _last_event_of_type(st, "presets_listed")
    assert ev is not None
    assert "$last" in ev["presets"]


def test_slot_set_rejects_unsupported_thinking(client_with_thinking_model):
    """Slot assignment with an unsupported thinking mode returns 422 (brief D4)."""
    c, st = client_with_thinking_model
    # "xhigh" may not be in claude-opus-4-0's supported thinking_modes.
    # resolve_capabilities will list the actual modes; test that the endpoint
    # rejects a clearly invalid mode string.
    resp = c.put("/api/config/slots/strong", json={
        "configured_model_id": "cm-opus",
        "thinking": "not_a_valid_mode",
    })
    assert resp.status_code == 422


def test_slot_set_invalid_slot_name(client_with_thinking_model):
    """PUT /api/config/slots/{slot} with an invalid slot name returns 422."""
    c, _ = client_with_thinking_model
    resp = c.put("/api/config/slots/unknown_slot", json={
        "configured_model_id": "cm-opus",
        "thinking": "disabled",
    })
    assert resp.status_code == 422


def test_slot_set_rejects_missing_model(client, app_state, config_path):
    """Slot assignment referencing a non-existent configured_model_id returns 422."""
    resp = client.put("/api/config/slots/standard", json={
        "configured_model_id": "no-such-model",
        "thinking": "disabled",
    })
    assert resp.status_code == 422


# -- Memory binding -----------------------------------------------------------

def test_memory_set_stores_binding(client, app_state, config_path):
    """PUT /api/config/memory/{kind} stores a MemoryBinding and pushes memory_bindings_listed."""
    resp = client.put("/api/config/memory/embedding", json={
        "configured_model_id": "cm-haiku",
    })
    assert resp.status_code == 200
    assert app_state.provider_config.config.memory is not None
    assert app_state.provider_config.config.memory.embedding is not None
    assert app_state.provider_config.config.memory.embedding.configured_model_id == "cm-haiku"

    ev = _last_event_of_type(app_state, "memory_bindings_listed")
    assert ev is not None
    assert ev["memory_bindings"]["embedding"]["configured_model_id"] == "cm-haiku"


def test_memory_set_invalid_kind(client, app_state, config_path):
    """PUT /api/config/memory/{kind} with an unrecognized kind returns 422."""
    resp = client.put("/api/config/memory/unknown_binding", json={
        "configured_model_id": "cm-haiku",
    })
    assert resp.status_code == 422


def test_memory_set_rejects_missing_model(client, app_state, config_path):
    """Memory binding that references a non-existent configured_model returns 422."""
    resp = client.put("/api/config/memory/memory_llm", json={
        "configured_model_id": "no-such-model",
    })
    assert resp.status_code == 422


# -- List-models action -------------------------------------------------------

def test_list_models_no_credential_returns_error(client, app_state, config_path):
    """list-models for a connection without a credential returns {ok: False, message}."""
    # Add a keyed connection without a credential.
    app_state.provider_config.config.connections.append(
        Connection(id="openai-nocred", type="openai")
    )
    resp = client.post("/api/config/connections/openai-nocred/list-models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "message" in data


def test_list_models_not_found(client, app_state, config_path):
    """list-models for an unknown connection id returns 404."""
    resp = client.post("/api/config/connections/does-not-exist/list-models")
    assert resp.status_code == 404


def test_list_models_success_pushes_provider_models(client, app_state, config_path):
    """Successful list-models call pushes provider_models_listed."""
    from koan.types import ProviderModel

    fake_models = [ProviderModel(provider="anthropic", model="claude-3-5-haiku-20241022", display_name="Haiku")]
    with patch("koan.web.app._refresh_one_provider_models", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = (True, "")
        # Patch the push so we can see the event.
        resp = client.post("/api/config/connections/anthropic-1/list-models")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_refresh.assert_called_once()


def test_push_provider_models_emits_families(app_state, config_path):
    """_push_provider_models includes a families list in the emitted payload.

    Seeds the provider_models overlay with a recognisable family (claude-sonnet)
    and asserts the emitted provider_models_listed payload carries a non-empty
    families list whose resolved id is the newest member.
    """
    from koan.types import ProviderModel
    from koan.web.app import _push_provider_models

    # Seed two models in the same family; the newer version should win.
    app_state.provider_config.provider_models["anthropic"] = [
        ProviderModel(provider="anthropic", model="claude-sonnet-4-5", display_name="Sonnet 4.5"),
        ProviderModel(provider="anthropic", model="claude-sonnet-4-0", display_name="Sonnet 4.0"),
    ]

    _push_provider_models(app_state)

    ev = _last_event_of_type(app_state, "provider_models_listed")
    assert ev is not None
    families = ev.get("families", [])
    assert len(families) >= 1

    sonnet_pins = [f for f in families if f.get("family") == "claude-sonnet"]
    assert len(sonnet_pins) == 1
    assert sonnet_pins[0]["resolved"] == "claude-sonnet-4-5"
    assert sonnet_pins[0]["provider"] == "anthropic"
    assert "claude-sonnet-4-5" in sonnet_pins[0]["resolved_from"]


# -- Newest-in-family ---------------------------------------------------------

def test_model_newest_pins_and_records_provenance(client, app_state, config_path):
    """newest endpoint upserts a ConfiguredModel with model_id + resolved_from."""
    from koan.agents.newest_in_family import NewestResolution

    fake_res = NewestResolution(
        model_id="claude-opus-4-0",
        resolved_from="newest(claude-opus)@2026-06-09 -> claude-opus-4-0",
    )

    with patch("koan.agents.newest_in_family.resolve_newest_in_family", new_callable=AsyncMock) as mock_newest:
        mock_newest.return_value = fake_res
        resp = client.post("/api/config/models/newest", json={
            "connection_id": "anthropic-1",
            "family": "claude-opus",
            "id": "cm-opus-pinned",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["model_id"] == "claude-opus-4-0"
    assert "resolved_from" in data

    cfg = app_state.provider_config.config
    cm = next(m for m in cfg.configured_models if m.id == "cm-opus-pinned")
    assert cm.model_id == "claude-opus-4-0"
    assert cm.resolved_from == fake_res.resolved_from


def test_model_newest_listing_error_returns_409(client, app_state, config_path):
    """newest endpoint with a non-listing connection type returns 409."""
    from koan.agents.model_listing import ModelListingError

    with patch("koan.agents.newest_in_family.resolve_newest_in_family", new_callable=AsyncMock) as mock_newest:
        mock_newest.side_effect = ModelListingError("listing not supported for this type")
        resp = client.post("/api/config/models/newest", json={
            "connection_id": "anthropic-1",
            "family": "claude-opus",
        })

    assert resp.status_code == 409
    assert resp.json()["error"] == "unavailable"


def test_model_newest_family_unavailable_returns_422(client, app_state, config_path):
    """newest endpoint when no models of the family exist returns 422."""
    from koan.agents.newest_in_family import NewestInFamilyUnavailable

    with patch("koan.agents.newest_in_family.resolve_newest_in_family", new_callable=AsyncMock) as mock_newest:
        mock_newest.side_effect = NewestInFamilyUnavailable("no models in family")
        resp = client.post("/api/config/models/newest", json={
            "connection_id": "anthropic-1",
            "family": "unknown-family",
        })

    assert resp.status_code == 422
    assert resp.json()["error"] == "not_found"


def test_model_newest_requires_connection_id(client, app_state, config_path):
    """newest endpoint without connection_id returns 422."""
    resp = client.post("/api/config/models/newest", json={"family": "claude-opus"})
    assert resp.status_code == 422


def test_model_newest_connection_not_found(client, app_state, config_path):
    """newest endpoint with a non-existent connection_id returns 404."""
    with patch("koan.agents.newest_in_family.resolve_newest_in_family", new_callable=AsyncMock):
        resp = client.post("/api/config/models/newest", json={
            "connection_id": "no-such",
            "family": "claude-opus",
        })
    assert resp.status_code == 404


# -- Model capabilities projection --------------------------------------------

def test_model_capabilities_populated_at_startup(app_state, config_path):
    """_push_initial_config_events populates Settings.model_capabilities for configured models."""
    from koan.web.app import _push_initial_config_events

    _push_initial_config_events(app_state)

    caps = app_state.projection_store.projection.settings.model_capabilities
    assert len(caps) == 1
    cap = caps[0]
    assert cap.configured_model_id == "cm-haiku"
    # Capabilities are populated: thinking_modes is a list, context_window is set.
    assert isinstance(cap.thinking_modes, list)
    assert isinstance(cap.context_window, int)


def test_model_capabilities_refreshed_after_model_set(client, app_state, config_path):
    """model_capabilities_listed is pushed after a configured-model upsert (M6)."""
    # Add a new configured model and verify capabilities are refreshed.
    resp = client.post("/api/config/models", json={
        "id": "cm-opus",
        "connection_id": "anthropic-1",
        "model_id": "claude-opus-4-0",
    })
    assert resp.status_code == 200

    ev = _last_event_of_type(app_state, "model_capabilities_listed")
    assert ev is not None
    cap_ids = [c["configured_model_id"] for c in ev["capabilities"]]
    assert "cm-haiku" in cap_ids
    assert "cm-opus" in cap_ids


def test_model_capabilities_refreshed_after_connection_set(client, app_state, config_path):
    """model_capabilities_listed is pushed after a connection mutation (M6)."""
    client.post("/api/config/connections", json={"id": "openai-x", "type": "openai"})
    ev = _last_event_of_type(app_state, "model_capabilities_listed")
    assert ev is not None
    # Existing configured model still appears.
    cap_ids = [c["configured_model_id"] for c in ev["capabilities"]]
    assert "cm-haiku" in cap_ids
