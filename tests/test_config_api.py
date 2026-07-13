# Tests for the M6 config mutation API and capability-surfacing projection.
#
# Coverage (M2: 13 settings events consolidated into one settings_listed snapshot):
#   - Connection upsert/delete: credential set/remove, settings_listed pushed
#   - Configured-model upsert/delete: settings_listed pushed (with identity + caps)
#   - Slot assignment: thinking validation (422 on unsupported), settings_listed pushed
#   - Memory binding set: settings_listed pushed
#   - List-models: success returns {ok: true, count}; no-credential returns {ok: False}
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
def tmp_key_path(koan_home):
    """Return the master key path in the test's temp home.

    The autouse koan_home fixture already redirects Path.home() so no
    monkeypatching is needed here; the key lives at koan_home / "master.key".
    """
    return koan_home / "master.key"


@pytest.fixture
def config_path(koan_home, monkeypatch):
    """Return the config YAML path in the test's temp home.

    Resets the write lock so async lock state from a prior test does not leak.
    No CONFIG_PATH setattr needed: the threaded save_koan_config derives the
    path from AppState.server.koan_home which the app_state fixture sets.
    """
    monkeypatch.setattr("koan.config._config_write_lock", None)
    return koan_home / "config.yaml"


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
def app_state(koan_home, tmp_key_path, conn, cm):
    """AppState with one connection, one configured model, and a credential store."""
    cfg = KoanConfig(
        connections=[conn],
        configured_models=[cm],
    )
    backend = FileKeyBackend(koan_home)
    store = CredentialStore(cfg, backend)
    store.set(conn.id, "test-api-key")

    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.credential_store = store
    # Thread the resolved home into server config so save handlers in the web
    # layer derive the correct config.yaml path via Path(st.server.koan_home).
    st.server.koan_home = str(koan_home)
    return st


@pytest.fixture
def client(app_state, config_path):
    """Test client with driver_main patched out."""
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state)
        with TestClient(app) as c:
            yield c


@pytest.fixture
def app_state_with_voyage(koan_home, tmp_key_path):
    """AppState with both anthropic and voyage connections for embedding-kind memory tests."""
    anthropic_conn = Connection(id="anthropic-1", type="anthropic")
    voyage_conn = Connection(id="voyage-1", type="voyage")
    anthropic_cm = ConfiguredModel(id="cm-haiku", connection_id="anthropic-1", model_id="claude-3-5-haiku-20241022")
    # voyage-4-large is a recognized Voyage embedding model (validated by the endpoint).
    voyage_cm = ConfiguredModel(id="cm-voyage", connection_id="voyage-1", model_id="voyage-4-large")
    cfg = KoanConfig(connections=[anthropic_conn, voyage_conn], configured_models=[anthropic_cm, voyage_cm])
    backend = FileKeyBackend(koan_home)
    store = CredentialStore(cfg, backend)
    store.set("anthropic-1", "test-api-key")
    store.set("voyage-1", "voyage-api-key")
    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.credential_store = store
    st.server.koan_home = str(koan_home)
    return st


@pytest.fixture
def client_with_voyage(app_state_with_voyage, config_path):
    """TestClient wired to app_state_with_voyage for embedding-kind memory binding tests."""
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state_with_voyage)
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

def test_connection_set_post_creates_connection_and_pushes_settings_listed(client, app_state, config_path):
    """POST /api/config/connections creates a new connection and pushes settings_listed."""
    resp = client.post("/api/config/connections", json={
        "id": "openai-1",
        "type": "openai",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cfg = app_state.provider_config.config
    ids = [c.id for c in cfg.connections]
    assert "openai-1" in ids

    ev = _last_event_of_type(app_state, "settings_listed")
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


def test_connection_delete_pushes_settings_listed(client, app_state, config_path):
    """DELETE /api/config/connections/{id} pushes settings_listed."""
    client.delete("/api/config/connections/anthropic-1")
    ev = _last_event_of_type(app_state, "settings_listed")
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


def test_model_set_pushes_settings_listed(client, app_state, config_path):
    """POST /api/config/models pushes settings_listed."""
    client.post("/api/config/models", json={
        "id": "cm-push-test",
        "connection_id": "anthropic-1",
        "model_id": "claude-opus-4-0",
    })
    ev = _last_event_of_type(app_state, "settings_listed")
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
def app_state_with_thinking_model(koan_home, tmp_key_path):
    """AppState with a claude-opus-4-0 model that supports thinking modes."""
    conn = Connection(id="anthropic-1", type="anthropic")
    # claude-opus-4-0 supports thinking in the capability table (thinking_modes populated).
    cm = ConfiguredModel(id="cm-opus", connection_id="anthropic-1", model_id="claude-opus-4-0")
    cfg = KoanConfig(connections=[conn], configured_models=[cm])
    backend = FileKeyBackend(koan_home)
    store = CredentialStore(cfg, backend)
    store.set("anthropic-1", "test-key")

    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.credential_store = store
    st.server.koan_home = str(koan_home)
    return st


@pytest.fixture
def client_with_thinking_model(app_state_with_thinking_model, monkeypatch):
    monkeypatch.setattr("koan.config._config_write_lock", None)
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state_with_thinking_model)
        with TestClient(app) as c:
            yield c, app_state_with_thinking_model


def test_slot_set_assigns_model_to_slot(client_with_thinking_model):
    """PUT /api/config/slots/{slot} writes a SlotAssignment and pushes settings_listed."""
    c, st = client_with_thinking_model
    resp = c.put("/api/config/slots/strong", json={
        "configured_model_id": "cm-opus",
        "thinking": "disabled",
    })
    assert resp.status_code == 200
    preset = st.provider_config.config.presets.get("$last")
    assert preset is not None
    assert preset.slots["strong"].configured_model_id == "cm-opus"

    ev = _last_event_of_type(st, "settings_listed")
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

def test_memory_set_stores_binding(client_with_voyage, app_state_with_voyage):
    """PUT /api/config/memory/embedding stores a MemoryBinding and pushes settings_listed.

    Uses the embedding kind with a voyage connection + recognized Voyage model
    (cm-voyage -> voyage-4-large), the only valid memory binding kind.
    """
    resp = client_with_voyage.put("/api/config/memory/embedding", json={
        "configured_model_id": "cm-voyage",
    })
    assert resp.status_code == 200
    assert app_state_with_voyage.provider_config.config.memory is not None
    assert app_state_with_voyage.provider_config.config.memory.embedding is not None
    assert app_state_with_voyage.provider_config.config.memory.embedding.configured_model_id == "cm-voyage"

    ev = _last_event_of_type(app_state_with_voyage, "settings_listed")
    assert ev is not None
    assert ev["memory_bindings"]["embedding"]["configured_model_id"] == "cm-voyage"


def test_memory_set_invalid_kind(client, app_state, config_path):
    """PUT /api/config/memory/{kind} with an unrecognized kind returns 422."""
    resp = client.put("/api/config/memory/unknown_binding", json={
        "configured_model_id": "cm-haiku",
    })
    assert resp.status_code == 422


def test_memory_set_rejects_missing_model(client, app_state, config_path):
    """Embedding binding that references a non-existent configured_model returns 422."""
    resp = client.put("/api/config/memory/embedding", json={
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


def test_list_models_success_returns_count(client, app_state, config_path):
    """Successful list-models call returns {ok: true, count: N}.

    The mock returns a 3-tuple (ok, msg, count); the endpoint unpacks it and
    includes count in the response so the Test badge can display the real number.
    """
    with patch("koan.web.app._refresh_one_provider_models", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = (True, "", 3)
        resp = client.post("/api/config/connections/anthropic-1/list-models")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 3
    mock_refresh.assert_called_once()


# test_push_provider_models_emits_families removed in M2: _push_provider_models
# is deleted (offerings come from the curated catalog via settings_listed).
# test_connection_save_schedules_background_refresh removed in M2: the
# post-save background model-list refresh is deleted.
# -- Newest-in-family section removed in M2: the /api/config/models/newest
# endpoint and async resolve_newest_in_family are deleted. Family grouping
# data now lives in offerings_by_connection identity fields.
# -- Model capabilities projection section removed in M2: the
# model_capabilities_listed event and Settings.model_capabilities field are
# deleted. Configured-model caps now travel inside settings_listed's
# configured_models entries (identity + caps).
