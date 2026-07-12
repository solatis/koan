# Tests for key web flows: SSE replay, SPA fallback, start-run, artifacts, path traversal.
#
# M5: profile CRUD and provider settings endpoints removed; start-run no longer
# requires a profile param.  Tests for deleted endpoints removed or replaced.

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from koan.config import KoanConfig
from koan.state import AppState
from koan.types import ConnectionStatus, ModelRegistryEntry
from koan.web.app import create_app


# -- Helpers ------------------------------------------------------------------

def _make_provider_status() -> list[ConnectionStatus]:
    """Build a minimal provider_status list for tests.

    M5: updated to use per-connection ConnectionStatus replacing per-type ProviderStatus.
    google connection is available; anthropic and openai are not.
    """
    return [
        ConnectionStatus(connection_id="google-direct", connection_type="google", available=True),
        ConnectionStatus(connection_id="anthropic-direct", connection_type="anthropic", available=False),
        ConnectionStatus(connection_id="openai-direct", connection_type="openai", available=False),
    ]


def _make_model_registry() -> list[ModelRegistryEntry]:
    """Build a minimal model registry for profile-CRUD tests.

    Provides one entry per provider tier so that model-ID and thinking-mode
    validation in _validate_profile_tiers can be exercised end-to-end.
    """
    return [
        ModelRegistryEntry(
            provider="google",
            model="gemini-2.5-pro",
            display_name="Gemini 2.5 Pro",
            context_window=1_000_000,
            thinking_modes=["low", "medium"],
        ),
        ModelRegistryEntry(
            provider="google",
            model="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            context_window=1_000_000,
            thinking_modes=["low"],
        ),
        ModelRegistryEntry(
            provider="google",
            model="gemini-2.5-flash-lite",
            display_name="Gemini 2.5 Flash Lite",
            context_window=1_000_000,
            thinking_modes=[],
        ),
    ]


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def app_state(koan_home):
    st = AppState()
    st.provider_config.config = KoanConfig()
    # Thread the resolved home so save handlers and _runs_dir use the temp dir.
    st.server.koan_home = str(koan_home)
    return st


@pytest.fixture
def client(app_state):
    # Patch driver_main to avoid spawning the real FSM
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state)
        with TestClient(app) as c:
            yield c


# -- SPA fallback (formerly landing page) -------------------------------------

def test_landing_page_renders(client, app_state):
    # After SPA migration, GET / serves the React app's index.html (or a
    # minimal placeholder when the frontend hasn't been built).
    resp = client.get("/")
    assert resp.status_code == 200
    assert "root" in resp.text


# -- Start run ----------------------------------------------------------------

def test_start_run_requires_task(client, app_state):
    resp = client.post("/api/start-run", json={"task": ""})
    assert resp.status_code == 422


def test_start_run_blocked_no_providers(client, app_state):
    # When no connection has credentials, start-run returns no_providers.
    # Provide a config with a valid preset so the unconfigured gate is passed.
    from koan.types import Connection, ConfiguredModel, Preset, SlotAssignment
    conn = Connection(id="g1", type="google")
    cm = ConfiguredModel(id="cm1", connection_id="g1", model_id="gemini-pro")
    slot = SlotAssignment(configured_model_id="cm1", thinking="disabled")
    preset = Preset(slots={"strong": slot, "standard": slot, "cheap": slot})
    from koan.config import KoanConfig
    app_state.provider_config.config = KoanConfig(
        connections=[conn],
        configured_models=[cm],
        presets={"$last": preset},
        active="$last",
    )
    app_state.provider_config.provider_status = [
        ConnectionStatus(connection_id="g1", connection_type="google", available=False),
    ]
    resp = client.post("/api/start-run", json={"task": "build something"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "no_providers"


# -- Start-run denormalization (run-config.yaml + frozen snapshot) ------------

def _make_openrouter_config():
    """Build a minimal KoanConfig with an openrouter connection.

    Availability is set manually via provider_status in each test; no Fernet
    credential is stored because the driver is patched out -- the start-run
    endpoint only freezes config and does not perform inference.
    """
    from koan.types import Connection, ConfiguredModel, Preset, SlotAssignment
    conn = Connection(id="or1", type="openrouter")
    cm = ConfiguredModel(id="cm-or", connection_id="or1", model_id="some-model")
    slot = SlotAssignment(configured_model_id="cm-or", thinking="disabled")
    preset = Preset(slots={"strong": slot, "standard": slot, "cheap": slot})
    return KoanConfig(
        connections=[conn],
        configured_models=[cm],
        presets={"$last": preset},
        active="$last",
    )


@pytest.mark.anyio
async def test_start_run_writes_run_config_yaml(tmp_path):
    """start-run writes <run_dir>/run-config.yaml as the durable frozen-config record.

    Assertions:
    (a) HTTP 200 and frozen_config is set on RunState.
    (b) run-config.yaml is written and parses back to a valid YAML dict.
    (c) The live cfg slot assignments are unchanged after start.
    (d) run-config.yaml contains no plaintext secrets (only ciphertext envelopes
        or empty credentials dict).
    """
    import yaml as _yaml
    from koan.web.app import create_app
    from starlette.testclient import TestClient

    cfg = _make_openrouter_config()
    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.provider_status = [
        ConnectionStatus(connection_id="or1", connection_type="openrouter", available=True),
    ]

    # _refresh_probe_state triggers build_model_registry() which calls into the
    # genai-prices bundled snapshot.  Patch it to avoid pre-existing snapshot errors
    # that affect all create_app lifespan tests.
    async def noop_refresh(app_state, broadcast=True):
        pass

    # write_run_config writes to the real ~/.koan/runs/<id>/ directory; this is
    # intentional -- the test verifies the actual file path returned by the API.
    # _push_model_capabilities is mocked because resolve_capabilities calls into
    # the capability resolver (not relevant to the file-write behavior under test).
    # CredentialStore.has is patched to avoid Fernet key I/O -- these tests cover
    # config freezing and file-write behavior, not credential validation.
    with patch("koan.driver.driver_main", new_callable=AsyncMock), \
         patch("koan.web.app._refresh_probe_state", side_effect=noop_refresh), \
         patch("koan.web.app._push_model_capabilities"), \
         patch("koan.credentials.CredentialStore.has", return_value=True):
        app = create_app(st)
        with TestClient(app) as client:
            resp = client.post("/api/start-run", json={"task": "build something"})

    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["ok"] is True
    run_dir = Path(data["run_dir"])

    # (a) frozen_config is set on RunState.
    assert st.run.frozen_config is not None

    # (b) run-config.yaml is written.
    run_cfg_path = run_dir / "run-config.yaml"
    assert run_cfg_path.exists(), f"run-config.yaml not found at {run_cfg_path}"
    parsed = _yaml.safe_load(run_cfg_path.read_text("utf-8"))
    assert isinstance(parsed, dict)
    assert "connections" in parsed

    # (c) Live cfg slot assignments are unchanged (deep copy was used).
    live_slot = cfg.presets["$last"].slots.get("strong")
    assert live_slot is not None
    assert live_slot.configured_model_id == "cm-or"  # not overridden

    # (d) No plaintext secret in run-config.yaml (credentials is empty; driver is patched).
    credentials = parsed.get("credentials", {})
    for key, envelope in credentials.items():
        # Each credential must be a Fernet envelope dict, never a raw string.
        assert isinstance(envelope, dict), f"credential for {key!r} is not an envelope dict"
        assert "scheme" in envelope and "ciphertext" in envelope


@pytest.mark.anyio
async def test_start_run_override_applies_to_frozen_config(tmp_path):
    """Per-run overrides appear in the frozen config but not in the live cfg.

    Assertions:
    (a) The strong slot in the frozen config points to 'override:strong'.
    (b) The live cfg strong slot is unchanged ('cm-or').
    (c) run-config.yaml reflects the override (contains the override cm id).
    """
    import yaml as _yaml
    from koan.web.app import create_app
    from starlette.testclient import TestClient

    cfg = _make_openrouter_config()
    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.provider_status = [
        ConnectionStatus(connection_id="or1", connection_type="openrouter", available=True),
    ]

    overrides = {
        "strong": {"connection_id": "or1", "model_id": "override-model", "thinking": "disabled"},
    }

    async def noop_refresh(app_state, broadcast=True):
        pass

    with patch("koan.driver.driver_main", new_callable=AsyncMock), \
         patch("koan.web.app._refresh_probe_state", side_effect=noop_refresh), \
         patch("koan.web.app._push_model_capabilities"), \
         patch("koan.credentials.CredentialStore.has", return_value=True):
        app = create_app(st)
        with TestClient(app) as client:
            resp = client.post("/api/start-run", json={"task": "do something", "overrides": overrides})

    assert resp.status_code == 200, resp.json()
    run_dir = Path(resp.json()["run_dir"])

    # (a) Frozen config has override:strong in the $last preset.
    frozen = st.run.frozen_config
    assert frozen is not None
    frozen_slot = frozen.presets["$last"].slots.get("strong")
    assert frozen_slot is not None
    assert frozen_slot.configured_model_id == "override:strong"

    # Verify the ephemeral configured-model exists in the frozen copy.
    override_cm = next((cm for cm in frozen.configured_models if cm.id == "override:strong"), None)
    assert override_cm is not None
    assert override_cm.model_id == "override-model"

    # (b) Live cfg is unchanged.
    live_slot = cfg.presets["$last"].slots.get("strong")
    assert live_slot is not None
    assert live_slot.configured_model_id == "cm-or"
    assert not any(cm.id == "override:strong" for cm in cfg.configured_models)

    # (c) run-config.yaml reflects the override.
    parsed = _yaml.safe_load((run_dir / "run-config.yaml").read_text("utf-8"))
    cm_ids = {cm["id"] for cm in parsed.get("configured_models", [])}
    assert "override:strong" in cm_ids


@pytest.mark.anyio
async def test_start_run_no_overrides_uses_persisted_slots(tmp_path):
    """start-run without overrides resolves model from the persisted $last preset."""
    from koan.web.app import create_app
    from starlette.testclient import TestClient

    cfg = _make_openrouter_config()
    st = AppState()
    st.provider_config.config = cfg
    st.provider_config.provider_status = [
        ConnectionStatus(connection_id="or1", connection_type="openrouter", available=True),
    ]

    async def noop_refresh(app_state, broadcast=True):
        pass

    with patch("koan.driver.driver_main", new_callable=AsyncMock), \
         patch("koan.web.app._refresh_probe_state", side_effect=noop_refresh), \
         patch("koan.web.app._push_model_capabilities"), \
         patch("koan.credentials.CredentialStore.has", return_value=True):
        app = create_app(st)
        with TestClient(app) as client:
            resp = client.post("/api/start-run", json={"task": "no overrides"})

    assert resp.status_code == 200, resp.json()

    frozen = st.run.frozen_config
    assert frozen is not None
    # No override:* configured-models in the frozen config.
    assert not any(cm.id.startswith("override:") for cm in frozen.configured_models)
    # Strong slot still points to the persisted cm-or.
    frozen_slot = frozen.presets["$last"].slots.get("strong")
    assert frozen_slot is not None
    assert frozen_slot.configured_model_id == "cm-or"


# -- Start-run preflight -------------------------------------------------------

def test_preflight_returns_unconfigured_when_no_preset(client, app_state):
    """Preflight returns 422 when no active preset is configured (M5)."""
    # Default KoanConfig has no presets; active='$last' won't resolve.
    resp = client.get("/api/start-run/preflight")
    assert resp.status_code == 422
    assert resp.json()["error"] == "unconfigured"


# (Removed with the CLI-binary model: preflight binary-validity, start-run
# missing-binary / unknown-installation-alias, /api/agents installation CRUD,
# and the CLI probe-refresh test. Provider availability is credential-based;
# there are no installations or binaries to validate.)


# -- Artifacts ----------------------------------------------------------------

def test_artifact_listing(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "landscape.md").write_text("# Landscape\n", "utf-8")
        app_state.run.run_dir = str(run_dir)

        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["path"] == "landscape.md"


def test_artifact_content(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "landscape.md").write_text("# Hello\n", "utf-8")
        app_state.run.run_dir = str(run_dir)

        resp = client.get("/api/artifacts/landscape.md")
        assert resp.status_code == 200
        data = resp.json()
        assert "# Hello" in data["content"]
        assert data["displayPath"] == "landscape.md"


def test_path_traversal_blocked(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        run_dir.mkdir(exist_ok=True)
        app_state.run.run_dir = str(run_dir)

        # URL-normalized traversal (../) is resolved before routing and hits the SPA fallback.
        # Use URL-encoded slashes (%2F) to test path traversal within the artifact handler.
        resp = client.get("/api/artifacts/..%2F..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)


# Profile CRUD tests removed in M5: /api/profiles endpoints deleted.
# See plan-milestone-5.md.

def test_profiles_endpoints_removed(client, app_state):
    """M5: profile CRUD endpoints removed; routes return 404 or SPA fallback."""
    # GET /api/profiles used to list profiles; now gone.
    resp = client.get("/api/profiles")
    # SPA fallback or 404/405 -- not a JSON profiles list.
    assert resp.status_code in (200, 404, 405)
    if resp.status_code == 200:
        ct = resp.headers.get("content-type", "")
        assert "text/html" in ct  # SPA, not JSON API


# -- api_artifact_comment endpoint -------------------------------------------

def test_api_artifact_comment_validates_path_and_comment(client, app_state):
    """POST /api/artifact-comment returns 422 on missing path or empty comment."""
    # Missing path
    resp = client.post("/api/artifact-comment", json={"comment": "hello"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "missing_path"

    # Missing comment
    resp = client.post("/api/artifact-comment", json={"path": "plan.md"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "missing_comment"

    # Empty comment string
    resp = client.post("/api/artifact-comment", json={"path": "plan.md", "comment": "  "})
    assert resp.status_code == 422
    assert resp.json()["error"] == "missing_comment"


def test_api_artifact_comment_enqueues_steering(client, app_state, tmp_path):
    """When no yield is active, the comment lands in steering_queue with artifact_path set."""
    app_state.run.run_dir = str(tmp_path)
    resp = client.post("/api/artifact-comment", json={
        "path": "plan.md",
        "comment": "Add a section on error handling",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Message enqueued with artifact_path tagged
    queue = app_state.interactions.steering_queue
    assert len(queue) == 1
    assert queue[0].artifact_path == "plan.md"
    assert "error handling" in queue[0].content


@pytest.mark.anyio
async def test_api_artifact_comment_resolves_active_yield(tmp_path):
    """When a yield is active, the comment resolves the yield future."""
    import asyncio
    from unittest.mock import patch, AsyncMock
    from koan.web.app import create_app
    from koan.state import AppState, AgentState
    from koan.phases import PhaseContext

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)

    agent = AgentState(
        agent_id="test-artifact-comment-yield",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        step=2,
        is_primary=True,
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
        event_log=AsyncMock(),
    )
    app_state.agents[agent.agent_id] = agent

    # Set an active yield future
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    app_state.interactions.yield_future = future

    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        from starlette.testclient import TestClient
        starlette_app = create_app(app_state)
        with TestClient(starlette_app) as client:
            resp = client.post("/api/artifact-comment", json={
                "path": "brief.md",
                "comment": "Add more detail to the decisions section",
            })
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    # The future must have been resolved (not still pending)
    assert future.done()
    # The comment lands in the user message buffer with artifact_path set
    assert any(
        m.artifact_path == "brief.md"
        for m in app_state.interactions.user_message_buffer
    )


def test_api_artifact_comment_commits_attachments(client, app_state, tmp_path):
    """Attachments are committed before the comment is enqueued."""
    from unittest.mock import patch
    app_state.run.run_dir = str(tmp_path)

    # commit_to_run is imported inline in the handler from koan.web.uploads;
    # patch at the source module rather than the caller's namespace.
    with patch("koan.web.uploads.commit_to_run") as mock_commit:
        resp = client.post("/api/artifact-comment", json={
            "path": "plan.md",
            "comment": "see screenshot",
            "attachments": ["upload-abc123"],
        })
        assert resp.status_code == 200
        mock_commit.assert_called_once()
        call_args = mock_commit.call_args
        # Second positional arg is the attachment IDs list
        assert call_args[0][1] == ["upload-abc123"]


# Profile CRUD tests (create/update/delete validations) removed in M5:
# /api/profiles endpoints deleted (plan-milestone-5.md).


# -- Provider settings endpoint (M3) -----------------------------------------
# Replaces the removed validate-provider and credential endpoints.


def _make_credential_store(config, koan_home):
    """Build an initialized CredentialStore backed by the test's temp koan home."""
    from koan.credentials import CredentialStore, FileKeyBackend
    return CredentialStore(config, FileKeyBackend(koan_home))


# api_settings_provider/delete/test tests removed in M5: endpoints deleted (plan-milestone-5.md).


def test_settings_provider_negative_presence(client, app_state):
    """Old credential and validate-provider routes return non-200 (removed in M3).

    Starlette may return 404 or 405 for a removed route depending on whether the
    catchall SPA fallback claims the method. Either status confirms the endpoint is
    gone: a 200 from the original handler would be the failure case.
    """
    resp_cred_post = client.post("/api/settings/credential", json={"provider": "google", "secret": "k"})
    assert resp_cred_post.status_code in (404, 405), (
        f"expected 404/405 for removed POST /api/settings/credential, got {resp_cred_post.status_code}"
    )

    resp_cred_del = client.delete("/api/settings/credential/google")
    assert resp_cred_del.status_code in (404, 405), (
        f"expected 404/405 for removed DELETE /api/settings/credential/google, got {resp_cred_del.status_code}"
    )

    resp_validate = client.post("/api/settings/validate-provider", json={"provider": "google"})
    assert resp_validate.status_code in (404, 405), (
        f"expected 404/405 for removed POST /api/settings/validate-provider, got {resp_validate.status_code}"
    )


# Provider test endpoint tests removed in M5: endpoint deleted (plan-milestone-5.md).


def test_settings_retry_accepts_valid_payload(client, app_state, monkeypatch):
    """PUT /api/settings/retry persists valid bounds and emits retry_settings_changed."""
    monkeypatch.setattr("koan.config._config_write_lock", None)

    resp = client.put("/api/settings/retry", json={"max_retry_attempts": 5, "max_retry_wait_seconds": 30})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    assert app_state.provider_config.config.max_retry_attempts == 5
    assert app_state.provider_config.config.max_retry_wait_seconds == 30.0
    assert any(
        e.event_type == "retry_settings_changed"
        for e in app_state.projection_store.events
    )


def test_settings_retry_rejects_invalid_attempts(client, app_state, monkeypatch):
    """PUT /api/settings/retry returns 422 when max_retry_attempts is out of range."""
    monkeypatch.setattr("koan.config._config_write_lock", None)

    resp = client.put("/api/settings/retry", json={"max_retry_attempts": 0, "max_retry_wait_seconds": 30})
    assert resp.status_code == 422

    resp = client.put("/api/settings/retry", json={"max_retry_attempts": 101, "max_retry_wait_seconds": 30})
    assert resp.status_code == 422


def test_settings_retry_rejects_invalid_wait(client, app_state, monkeypatch):
    """PUT /api/settings/retry returns 422 when max_retry_wait_seconds is out of range."""
    monkeypatch.setattr("koan.config._config_write_lock", None)

    resp = client.put("/api/settings/retry", json={"max_retry_attempts": 5, "max_retry_wait_seconds": 0})
    assert resp.status_code == 422

    resp = client.put("/api/settings/retry", json={"max_retry_attempts": 5, "max_retry_wait_seconds": 601})
    assert resp.status_code == 422


def test_settings_body_includes_retry_fields(client, app_state):
    """GET /api/settings/body includes maxRetryAttempts and maxRetryWaitSeconds."""
    resp = client.get("/api/settings/body")
    assert resp.status_code == 200
    body = resp.json()
    assert "maxRetryAttempts" in body, "expected maxRetryAttempts in settings body"
    assert "maxRetryWaitSeconds" in body, "expected maxRetryWaitSeconds in settings body"
    assert body["maxRetryAttempts"] == 10
    assert body["maxRetryWaitSeconds"] == 60.0


def test_connection_set_accepts_openrouter(client, app_state):
    """POST /api/config/connections accepts type='openrouter', validates _VALID_CONNECTION_TYPES.

    openrouter is key-requiring; no base_url or region field is sent. This test
    verifies that the type passes validation and the connection is persisted --
    no live model listing is triggered or asserted here.
    """
    from koan.web.app import _VALID_CONNECTION_TYPES
    assert "openrouter" in _VALID_CONNECTION_TYPES, (
        "_VALID_CONNECTION_TYPES does not contain 'openrouter'"
    )
    resp = client.post("/api/config/connections", json={
        "id": "openrouter-1",
        "type": "openrouter",
    })
    assert resp.status_code == 200, resp.json()
    assert resp.json()["ok"] is True
    cfg = app_state.provider_config.config
    conn_ids = [c.id for c in cfg.connections]
    assert "openrouter-1" in conn_ids


# -- Agent installation endpoints removed (M3) --------------------------------

def test_agents_create_removed(client, app_state):
    """M3: POST /api/agents endpoint was deleted; the SPA fallback serves HTML."""
    resp = client.post("/api/agents", json={
        "alias": "my-claude", "runner_type": "claude",
        "binary": "/usr/bin/claude", "extra_args": [],
    })
    # Starlette routes POST /api/agents to nothing; SPA fallback or 405
    assert resp.status_code in (200, 404, 405)


def test_agents_detect_removed(client, app_state):
    """M3: /api/agents/detect endpoint was deleted; SPA fallback serves HTML."""
    resp = client.get("/api/agents/detect?runner_type=claude")
    # Route gone: SPA serves the React app (200 HTML) rather than a JSON response
    assert resp.status_code in (200, 404, 405)
    if resp.status_code == 200:
        assert "root" in resp.text  # HTML, not JSON


def test_agents_installation_form_removed(client, app_state):
    """M3: /api/settings/installation-form endpoint was deleted."""
    resp = client.get("/api/settings/installation-form")
    assert resp.status_code in (200, 404, 405)


# -- SSE replay ---------------------------------------------------------------

def test_sse_replay(app_state):
    """SSE stream sends a snapshot and the protocol uses push_event / get_snapshot."""
    from koan.web.app import _sse_event

    # Prime with a run_started so phase_started has a run to update
    app_state.projection_store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
    app_state.projection_store.push_event("phase_started", {"phase": "intake"})

    # Verify projection holds the phase in the new nested location
    assert app_state.projection_store.projection.run is not None
    assert app_state.projection_store.projection.run.phase == "intake"
    assert app_state.projection_store.version == 2

    # Verify the SSE event formatter produces correct output
    event_str = _sse_event("snapshot", app_state.projection_store.get_snapshot())
    assert "event: snapshot" in event_str
    assert '"intake"' in event_str

    # Verify audit log retains events
    assert len(app_state.projection_store.events) == 2
    assert app_state.projection_store.events[1].event_type == "phase_started"


# -- Live page redirect (now SPA fallback) ------------------------------------

def test_live_page_when_running(client, app_state):
    # After SPA migration, GET / always returns the SPA entry point.
    # The React app reads store state client-side to render the live view.
    app_state.run.run_dir = "/tmp/fake-run"
    app_state.run.phase = "intake"

    resp = client.get("/")
    assert resp.status_code == 200
    assert "root" in resp.text



# -- Old model-config route removed ------------------------------------------

def test_model_config_removed(client, app_state):
    # After SPA migration, unknown paths are served by the SPA fallback (200).
    # The /api/model-config endpoint no longer exists as a JSON API endpoint.
    resp = client.get("/api/model-config")
    # SPA fallback serves HTML, not a JSON API response
    assert resp.status_code in (200, 404, 405)
    if resp.status_code == 200:
        # Must be HTML (SPA), not a JSON API response
        ct = resp.headers.get("content-type", "")
        assert "text/html" in ct


# -- Landing page: profile selector & settings button ------------------------

def test_landing_with_connection_status(client, app_state):
    # GET / serves the React SPA regardless of connection status.
    app_state.provider_config.provider_status = _make_provider_status()
    resp = client.get("/")
    assert resp.status_code == 200


def test_landing_start_run_disabled_no_connections(client, app_state):
    # After SPA migration, connection availability is checked client-side via /api/probe.
    app_state.provider_config.provider_status = [
        ConnectionStatus(connection_id="c1", connection_type="openai", available=False),
    ]
    resp = client.get("/")
    assert resp.status_code == 200


# test_start_run_sends_profile removed in M5: profile param removed from start-run.
# test_start_run_unknown_profile_rejected removed in M5: profile param removed.


# -- Probe refresh ------------------------------------------------------------

class TestProbeRefresh:
    def test_probe_returns_connection_status(self, client, app_state):
        """M5: /api/probe returns {connections: [...]} with per-connection availability."""
        app_state.provider_config.provider_status = _make_provider_status()
        resp = client.get("/api/probe")
        assert resp.status_code == 200
        data = resp.json()
        assert "connections" in data
        # 3 connections from _make_provider_status
        assert len(data["connections"]) == 3
        # Each connection has the required fields
        for conn in data["connections"]:
            assert "connection_id" in conn
            assert "connection_type" in conn
            assert "available" in conn



# -- SSE endpoint HTTP-level tests -------------------------------------------

@pytest.mark.anyio
def test_sse_snapshot_contains_projection_state(app_state):
    """Snapshot SSE event contains the full camelCase projection as {version, state}."""
    from koan.web.app import _sse_event

    app_state.projection_store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
    app_state.projection_store.push_event("phase_started", {"phase": "intake"})

    snapshot = app_state.projection_store.get_snapshot()
    assert snapshot["version"] == 2
    # New model: phase lives inside run
    assert snapshot["state"]["run"]["phase"] == "intake"
    # New model: top-level fields are settings, run, notifications
    assert "settings" in snapshot["state"]
    assert "notifications" in snapshot["state"]

    # Verify SSE wire format
    event_str = _sse_event("snapshot", snapshot)
    assert "event: snapshot" in event_str
    assert '"intake"' in event_str


def test_sse_audit_log_retains_events(app_state):
    """Audit log retains all events in order; reconnecting clients get a fresh snapshot."""
    app_state.projection_store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
    app_state.projection_store.push_event("phase_started", {"phase": "intake"})
    app_state.projection_store.push_event("phase_started", {"phase": "brief-generation"})
    # version is now 3

    assert len(app_state.projection_store.events) == 3
    assert app_state.projection_store.version == 3

    # Last event is in the log
    last = app_state.projection_store.events[-1]
    assert last.event_type == "phase_started"
    assert last.payload["phase"] == "brief-generation"

    # Projection reflects latest state
    assert app_state.projection_store.projection.run.phase == "brief-generation"

    # Snapshot for reconnect reflects full current state
    snap = app_state.projection_store.get_snapshot()
    assert snap["version"] == 3
    assert snap["state"]["run"]["phase"] == "brief-generation"


def test_sse_always_snapshot_on_version_mismatch(app_state):
    """Any since != server.version triggers a fresh snapshot (no fatal_error)."""
    store = app_state.projection_store
    assert store.version == 0

    # Any client version (stale or ahead) gets a snapshot. No fatal_error.
    # The server simply sends its current state.
    snap = store.get_snapshot()
    assert snap["version"] == 0
    assert snap["state"]["run"] is None

    # Advance server
    store.push_event("run_started", {"profile": "balanced", "installations": {}, "scout_concurrency": 8})
    assert store.version == 1

    # Client at since=99 (> server) still gets a valid snapshot
    # (sse_stream sends snapshot when since != store.version)
    snap2 = store.get_snapshot()
    assert snap2["version"] == 1
    assert snap2["state"]["run"] is not None


# -- koan_artifact_write -------------------------------------------------------

def _make_orchestrator_agent(tmp_path, agent_id="test-write"):
    """Build a minimal orchestrator AgentState for handler tests."""
    from unittest.mock import AsyncMock
    from koan.state import AgentState, AppState
    from koan.phases import PhaseContext

    app_state = AppState()
    app_state.server.yolo = True
    app_state.run.phase = "plan"
    app_state.run.run_dir = str(tmp_path)

    agent = AgentState(
        agent_id=agent_id,
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir=str(tmp_path),
        step=2,
        is_primary=True,
        phase_ctx=PhaseContext(run_dir=str(tmp_path), subagent_dir=str(tmp_path)),
        event_log=AsyncMock(),
    )
    app_state.agents[agent.agent_id] = agent
    return app_state, agent


@pytest.mark.anyio
async def test_artifact_write_creates_plain_file(tmp_path):
    """koan_artifact_write writes the body verbatim -- artifacts have no frontmatter.

    Uses brief.md in the intake phase (unreviewed family, no reviewer spawn).
    """
    from koan.tools.koan_tools import ToolDeps, artifact_write_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-write-plain")
    # brief.md is only legal in the intake phase (validated by the registry in M3).
    app_state.run.phase = "intake"
    deps = ToolDeps(app_state=app_state, agent=agent)

    result = await artifact_write_core(deps, "brief.md", "hello")

    assert (tmp_path / "brief.md").exists()
    text = (tmp_path / "brief.md").read_text()
    # Plain file: the body is on disk verbatim, no YAML frontmatter preamble.
    assert text == "hello"
    assert not text.startswith("---")

    # Return value is ok=True JSON string (cores return str, not content blocks).
    import json
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["filename"] == "brief.md"


@pytest.mark.anyio
async def test_artifact_write_emits_diff_events(tmp_path):
    """koan_artifact_write triggers artifact_diff so the sidebar refreshes."""
    from koan.tools.koan_tools import ToolDeps, artifact_write_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-write-diff")
    app_state.run.phase = "intake"  # brief.md is valid in intake (M3 registry validation)
    await artifact_write_core(ToolDeps(app_state=app_state, agent=agent), "brief.md", "hello")

    event_types = [e.event_type for e in app_state.projection_store.events]
    assert any(t in event_types for t in ("artifact_created", "artifact_modified", "artifact_diff"))


@pytest.mark.anyio
async def test_artifact_write_does_not_emit_review_events(tmp_path):
    """koan_artifact_write must not emit review_started or review_cleared."""
    from koan.tools.koan_tools import ToolDeps, artifact_write_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-write-noreview")
    app_state.run.phase = "intake"  # brief.md is valid in intake (M3 registry validation)
    await artifact_write_core(ToolDeps(app_state=app_state, agent=agent), "brief.md", "hello")

    event_types = [e.event_type for e in app_state.projection_store.events]
    assert "artifact_review_started" not in event_types
    assert "artifact_review_cleared" not in event_types


@pytest.mark.anyio
async def test_artifact_write_does_not_block(tmp_path):
    """koan_artifact_write returns immediately (non-blocking)."""
    from koan.tools.koan_tools import ToolDeps, artifact_write_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-write-noblock")
    app_state.run.phase = "intake"  # brief.md is valid in intake (M3 registry validation)
    result = await artifact_write_core(ToolDeps(app_state=app_state, agent=agent), "brief.md", "hello")
    assert result is not None


@pytest.mark.anyio
async def test_artifact_write_does_not_block_2(tmp_path):
    """koan_artifact_write returns immediately without a status argument."""
    from koan.tools.koan_tools import ToolDeps, artifact_write_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-write-noarg")
    app_state.run.phase = "intake"  # brief.md is valid in intake (M3 registry validation)
    result = await artifact_write_core(ToolDeps(app_state=app_state, agent=agent), "brief.md", "content")
    assert result is not None


def _body_anchor_token(body: str, line_index: int) -> str:
    """Build the '{anchor}§{line}' token for a 0-based body line (as read emits).

    Used by the edit tests to construct the anchor argument from known body content
    without going through a full artifact_read_core round-trip.
    """
    from koan.tools.line_anchors import ANCHOR_DELIMITER, compute_anchors

    lines = body.splitlines()
    anchors = compute_anchors(lines)
    return f"{anchors[line_index]}{ANCHOR_DELIMITER}{lines[line_index]}"


@pytest.mark.anyio
async def test_artifact_read_returns_anchored_content(tmp_path):
    """koan_artifact_read returns anchored, line-numbered content of the artifact.

    The file is written directly (bypassing artifact_write_core) because this
    test exercises artifact_read_core mechanics, not the write path.
    """
    from koan.tools.koan_tools import ToolDeps, artifact_read_core
    from koan.tools.line_anchors import ANCHOR_DELIMITER

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-read")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about reading, not about the
    # M3 write-once validation or reviewer spawning.
    (tmp_path / "doc.md").write_text("# Hello\nbody text\n", encoding="utf-8")

    # Anchored output: "{lineno}\t{anchor}§{content}".
    returned_text = await artifact_read_core(deps, "doc.md")
    lines = returned_text.splitlines()
    assert lines[0].startswith("1\t") and lines[0].endswith(f"{ANCHOR_DELIMITER}# Hello")
    assert lines[1].startswith("2\t") and lines[1].endswith(f"{ANCHOR_DELIMITER}body text")


@pytest.mark.anyio
async def test_artifact_read_rejects_path_traversal(tmp_path):
    """koan_artifact_read confines to run_dir -- a traversal filename is rejected."""
    from koan.tools.koan_tools import ToolDeps, artifact_read_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-read-traversal")
    deps = ToolDeps(app_state=app_state, agent=agent)

    with pytest.raises(ValueError) as exc_info:
        await artifact_read_core(deps, "../escape.md")
    # The slash guard fires before resolution; either way it is rejected.
    assert "invalid_filename:" in str(exc_info.value) or "invalid_path:" in str(exc_info.value)


@pytest.mark.anyio
async def test_artifact_read_large_artifact_no_rejection(tmp_path):
    """koan_artifact_read is trusted and exempt from the output cap.

    Writes an artifact whose body exceeds 500 lines, then reads it via
    artifact_read_core and asserts the full content is returned (no
    'tool result too large' error). Guards Decision 6 / limit=None trusted bypass.

    The file is written directly (bypassing artifact_write_core) because the
    filename "large.md" is not in the M3 artifact grammar; this test exercises
    artifact_read_core's size handling, not the write path.
    """
    from koan.tools.koan_tools import ToolDeps, artifact_read_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-read-large")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # 600 lines -- well over the 500-line default cap for untrusted tools.
    body = "\n".join(f"line {i}" for i in range(600)) + "\n"
    # Write directly so we test read mechanics with arbitrary content, not the
    # M3 write-once validation (which only allows grammar-conformant names).
    (tmp_path / "large.md").write_text(body, encoding="utf-8")

    result = await artifact_read_core(deps, "large.md")

    # Must not be a rejection message.
    assert "tool result too large" not in result
    # Must contain first and last lines in anchored format.
    result_lines = result.splitlines()
    assert result_lines[0].endswith("line 0")
    assert result_lines[599].endswith("line 599")


@pytest.mark.anyio
async def test_artifact_list_omits_status(tmp_path):
    """koan_artifact_list JSON carries path/size/modified_at, no status field."""
    import json
    from koan.tools.koan_tools import ToolDeps, artifact_list_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-list-no-status")

    (tmp_path / "one.md").write_text("body\n")
    (tmp_path / "two.md").write_text("# No frontmatter\n")

    result = await artifact_list_core(ToolDeps(app_state=app_state, agent=agent))
    payload = json.loads(result)
    by_path = {a["path"]: a for a in payload["artifacts"]}

    assert "status" not in by_path["one.md"]
    assert "status" not in by_path["two.md"]
    assert "path" in by_path["one.md"]
    assert "size" in by_path["one.md"]
    assert "modified_at" in by_path["one.md"]


# -- koan_artifact_edit -------------------------------------------------------

@pytest.mark.anyio
async def test_artifact_edit_replaces_anchored_line(tmp_path):
    """koan_artifact_edit replaces the anchored line and updates the body.

    The file is written directly (bypassing artifact_write_core) because this
    test exercises edit mechanics, not the M3 write-once validation.
    """
    import json
    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-replace")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about editing, not about the M3 write path.
    (tmp_path / "doc.md").write_text("hello world\n", encoding="utf-8")

    token = _body_anchor_token("hello world\n", 0)
    result = await artifact_edit_core(deps, "doc.md", token, "hello koan")
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["filename"] == "doc.md"

    body = (tmp_path / "doc.md").read_text()
    assert body == "hello koan\n"
    assert "world" not in body


@pytest.mark.anyio
async def test_artifact_edit_disambiguates_duplicate_lines(tmp_path):
    """Identical body lines get distinct anchors; editing one leaves the others."""
    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-dup")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about edit disambiguation, not write path.
    (tmp_path / "doc.md").write_text("foo\nfoo\n", encoding="utf-8")
    # Edit the second 'foo' (index 1) only -- the ~2 ordinal anchor.
    token = _body_anchor_token("foo\nfoo\n", 1)
    await artifact_edit_core(deps, "doc.md", token, "baz")

    assert (tmp_path / "doc.md").read_text() == "foo\nbaz\n"


@pytest.mark.anyio
async def test_artifact_edit_then_read_round_trip(tmp_path):
    """An anchor from koan_artifact_read resolves in koan_artifact_edit; the change sticks."""
    from koan.tools.koan_tools import (
        ToolDeps, artifact_read_core, artifact_edit_core,
    )
    from koan.tools.line_anchors import ANCHOR_DELIMITER

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-roundtrip")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about the read->anchor->edit round trip.
    (tmp_path / "doc.md").write_text("alpha\nbeta\n", encoding="utf-8")

    # Take the anchor straight from read output (not a precomputed helper).
    read_out = await artifact_read_core(deps, "doc.md")
    line2 = read_out.splitlines()[1]            # "2\t{anchor}§beta"
    token = line2.split("\t", 1)[1]             # "{anchor}§beta"
    assert token.endswith(f"{ANCHOR_DELIMITER}beta")

    await artifact_edit_core(deps, "doc.md", token, "BETA")
    assert (tmp_path / "doc.md").read_text() == "alpha\nBETA\n"


@pytest.mark.anyio
async def test_artifact_edit_file_not_found(tmp_path):
    """koan_artifact_edit returns a not_found envelope for a missing file.

    Recoverable validation failures are returned as {"ok": false} envelopes
    rather than raised so the run is not crashed by a model mistake.
    """
    import json
    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-notfound")
    deps = ToolDeps(app_state=app_state, agent=agent)

    result = await artifact_edit_core(deps, "missing.md", "deadbeef§x", "new")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "not_found"


@pytest.mark.anyio
async def test_artifact_edit_anchor_not_found(tmp_path):
    """koan_artifact_edit returns a recoverable envelope when the anchor is absent from the body."""
    import json

    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-nomatch")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about anchor resolution, not write path.
    (tmp_path / "doc.md").write_text("hello world\n", encoding="utf-8")

    result = await artifact_edit_core(deps, "doc.md", "deadbeef§nonexistent", "x")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "edit_failed"
    assert "not found" in payload["error"]["message"]


@pytest.mark.anyio
async def test_artifact_edit_content_mismatch(tmp_path):
    """koan_artifact_edit returns a recoverable envelope on inline-content drift."""
    import json

    from koan.tools.koan_tools import ToolDeps, artifact_edit_core
    from koan.tools.line_anchors import ANCHOR_DELIMITER, compute_anchors

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-drift")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about content-mismatch detection.
    (tmp_path / "doc.md").write_text("real line\n", encoding="utf-8")
    anchor = compute_anchors(["real line"])[0]

    result = await artifact_edit_core(deps, "doc.md", f"{anchor}{ANCHOR_DELIMITER}WRONG", "x")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "edit_failed"
    assert "mismatch" in payload["error"]["message"]


@pytest.mark.anyio
async def test_artifact_edit_invalid_edit_type(tmp_path):
    """koan_artifact_edit returns a recoverable envelope for an unknown edit_type."""
    import json

    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-badtype")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about edit_type validation.
    (tmp_path / "doc.md").write_text("content\n", encoding="utf-8")
    token = _body_anchor_token("content\n", 0)

    result = await artifact_edit_core(deps, "doc.md", token, "new", edit_type="frobnicate")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "edit_failed"


@pytest.mark.anyio
async def test_artifact_edit_insert_after_appends(tmp_path):
    """koan_artifact_edit insert_after on the last line appends to end-of-file."""
    import json

    from koan.tools.koan_tools import ToolDeps, artifact_edit_core
    from koan.tools.line_anchors import ANCHOR_DELIMITER, compute_anchors

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-append")
    deps = ToolDeps(app_state=app_state, agent=agent)

    (tmp_path / "doc.md").write_text("line one\nline two\n", encoding="utf-8")
    token = f"{compute_anchors(['line one', 'line two'])[1]}{ANCHOR_DELIMITER}line two"

    result = await artifact_edit_core(
        deps, "doc.md", token, "\n## Review\nappended", edit_type="insert_after"
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    body = (tmp_path / "doc.md").read_text(encoding="utf-8")
    assert body.endswith("## Review\nappended\n")


@pytest.mark.anyio
async def test_artifact_edit_emits_diff_events(tmp_path):
    """koan_artifact_edit triggers artifact_diff so the sidebar refreshes."""
    from koan.tools.koan_tools import ToolDeps, artifact_edit_core

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-edit-diff")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Write the file directly -- this test is about edit diff events, not write path.
    (tmp_path / "doc.md").write_text("before edit\n", encoding="utf-8")
    # Clear events recorded during write so we can isolate the edit's events
    events_before = len(app_state.projection_store.events)

    token = _body_anchor_token("before edit\n", 0)
    await artifact_edit_core(deps, "doc.md", token, "after edit")

    new_event_types = [
        e.event_type for e in app_state.projection_store.events[events_before:]
    ]
    assert any(t in new_event_types for t in ("artifact_created", "artifact_modified", "artifact_diff"))


# -- api_sessions_list: workflow_history schema --------------------------------

def test_api_sessions_list_returns_workflow_from_history(koan_home, client):
    """api_sessions_list derives the workflow field from workflow_history[-1]["name"]."""
    # Create the run dir under koan_home/runs/ so _runs_dir(st) finds it.
    run_dir = koan_home / "runs" / "2099000000-aabbccdd"
    run_dir.mkdir(parents=True)
    (run_dir / "task.json").write_text(json.dumps({
        "task": "build something",
        "workflow_history": [{"name": "plan", "phase": "intake", "started_at": 0.0}],
        "created_at": 0.0,
        "project_dir": "/some/project",
    }))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["workflow"] == "plan"


def test_api_sessions_list_handles_empty_history(koan_home, client):
    """api_sessions_list returns workflow='' and does not crash when workflow_history is empty."""
    run_dir = koan_home / "runs" / "2099000001-aabbccdd"
    run_dir.mkdir(parents=True)
    (run_dir / "task.json").write_text(json.dumps({
        "task": "build something",
        "workflow_history": [],
        "created_at": 0.0,
        "project_dir": "/some/project",
    }))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["workflow"] == ""


# -- koan_set_workflow handler -------------------------------------------------

@pytest.mark.anyio
async def test_koan_set_workflow_swaps_app_state_and_appends_history(tmp_path):
    """koan_set_workflow swaps app_state.run.workflow and appends a history entry to task.json."""
    from koan.lib.workflows import get_workflow
    from koan.tools.koan_tools import ToolDeps, apply_set_workflow

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-set-workflow")
    # Set up the run with the "plan" workflow so the transition makes sense.
    app_state.run.workflow = get_workflow("plan")

    # Write a task.json with a single workflow_history entry (as driver_main would).
    (tmp_path / "task.json").write_text(json.dumps({
        "workflow_history": [{"name": "plan", "phase": "intake", "started_at": 0.0}],
    }))

    deps = ToolDeps(app_state=app_state, agent=agent)
    # apply_set_workflow returns a plain string (no content blocks).
    result = await apply_set_workflow(deps, "milestones")

    # app_state should reflect the new workflow.
    assert app_state.run.workflow.name == "milestones"
    assert app_state.run.phase == "intake"

    # task.json on disk should have two history entries.
    import json as _json
    task_dict = _json.loads((tmp_path / "task.json").read_text())
    history = task_dict["workflow_history"]
    assert len(history) == 2
    assert history[0]["name"] == "plan"
    assert history[1]["name"] == "milestones"
    assert history[1]["phase"] == "intake"

    # Return value mentions the new workflow and phase.
    assert "milestones" in result
    assert "intake" in result


@pytest.mark.anyio
async def test_koan_set_workflow_unknown_workflow_returns_envelope(tmp_path):
    """koan_set_workflow returns the unknown_workflow envelope for an unregistered name."""
    import json
    import json as _json
    from koan.tools.koan_tools import ToolDeps, apply_set_workflow

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-set-workflow-bad")
    (tmp_path / "task.json").write_text(_json.dumps({
        "workflow_history": [{"name": "plan", "phase": "intake", "started_at": 0.0}],
    }))

    deps = ToolDeps(app_state=app_state, agent=agent)

    # unknown_workflow is now a recoverable envelope, not a raise.
    result = await apply_set_workflow(deps, "nonexistent")
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "unknown_workflow"


@pytest.mark.anyio
async def test_koan_set_workflow_emits_projection_events(tmp_path):
    """koan_set_workflow emits workflow_selected, phase_started, yield_cleared, agent_step_advanced in order."""
    import json as _json
    from koan.lib.workflows import get_workflow
    from koan.tools.koan_tools import ToolDeps, apply_set_workflow

    app_state, agent = _make_orchestrator_agent(tmp_path, "test-set-workflow-events")
    app_state.run.workflow = get_workflow("plan")
    (tmp_path / "task.json").write_text(_json.dumps({
        "workflow_history": [{"name": "plan", "phase": "intake", "started_at": 0.0}],
    }))

    deps = ToolDeps(app_state=app_state, agent=agent)

    # Record projection events emitted during the call.
    events_before = len(app_state.projection_store.events)
    await apply_set_workflow(deps, "milestones")
    new_events = app_state.projection_store.events[events_before:]

    event_types = [e.event_type for e in new_events]
    # workflow_selected must come before phase_started (fold order matters).
    assert "workflow_selected" in event_types
    assert "phase_started" in event_types
    assert "yield_cleared" in event_types
    assert "agent_step_advanced" in event_types

    wf_idx = event_types.index("workflow_selected")
    ph_idx = event_types.index("phase_started")
    assert wf_idx < ph_idx, "workflow_selected must precede phase_started"

    # Payload checks.
    wf_event = new_events[wf_idx]
    assert wf_event.payload.get("workflow") == "milestones"
    ph_event = new_events[ph_idx]
    assert ph_event.payload.get("phase") == "intake"

# -- Mechanical phase/workflow transition routes -------------------------------


def _setup_parked_yield(app_state):
    """Set up app_state with a run_dir, a pending yield_future, and a primary agent."""
    import asyncio
    from koan.state import AgentState

    app_state.run.run_dir = "/tmp/test-run"
    loop = asyncio.new_event_loop()
    app_state.interactions.yield_future = loop.create_future()
    agent = AgentState(
        agent_id="primary-test", role="orchestrator", subagent_dir="/tmp/test-sub",
        is_primary=True,
    )
    app_state.agents[agent.agent_id] = agent
    return agent


def test_api_set_phase_happy_path(client, app_state):
    """POST /api/phase with a valid phase transitions and resolves the yield_future."""
    from koan.lib.workflows import get_workflow

    app_state.run.workflow = get_workflow("plan")
    app_state.run.phase = "intake"
    agent = _setup_parked_yield(app_state)

    resp = client.post("/api/phase", json={"phase": "plan"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["phase"] == "plan"
    # Phase updated by the shared core.
    assert app_state.run.phase == "plan"
    # yield_future resolved.
    assert app_state.interactions.yield_future is not None
    assert app_state.interactions.yield_future.done()
    # mechanical_resume was set as the claim (the loop clears it on resume).
    assert app_state.interactions.mechanical_resume is True


def test_api_set_phase_done(client, app_state):
    """POST /api/phase with 'done' triggers server-authoritative workflow end."""
    from koan.lib.workflows import get_workflow

    app_state.run.workflow = get_workflow("plan")
    app_state.run.phase = "plan"
    _setup_parked_yield(app_state)

    resp = client.post("/api/phase", json={"phase": "done"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # workflow_done set.
    assert app_state.run.workflow_done is True

    # Event sequence: workflow_completed strictly before run_cleared.
    event_types = [e.event_type for e in app_state.projection_store.events]
    assert "workflow_completed" in event_types
    assert "run_cleared" in event_types
    assert event_types.index("workflow_completed") < event_types.index("run_cleared")

    # Interaction buffers cleared by finalize_workflow_end.
    assert app_state.interactions.user_message_buffer == []
    assert app_state.interactions.steering_queue == []


def test_api_set_phase_no_run(client, app_state):
    """POST /api/phase with no run_dir returns 409 no_run."""
    resp = client.post("/api/phase", json={"phase": "plan"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "no_run"


def test_api_set_phase_not_at_yield(client, app_state):
    """POST /api/phase when no yield is pending returns 409 not_at_yield."""
    app_state.run.run_dir = "/tmp/test-run"
    app_state.interactions.yield_future = None
    resp = client.post("/api/phase", json={"phase": "plan"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "not_at_yield"


def test_api_set_phase_invalid_transition(client, app_state):
    """POST /api/phase with an invalid phase returns 422 invalid_transition."""
    from koan.lib.workflows import get_workflow

    app_state.run.workflow = get_workflow("plan")
    app_state.run.phase = "intake"
    _setup_parked_yield(app_state)

    resp = client.post("/api/phase", json={"phase": "nonexistent"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_transition"


def test_api_set_phase_missing_body_key(client, app_state):
    """POST /api/phase with no 'phase' key returns 422."""
    app_state.run.run_dir = "/tmp/test-run"
    _setup_parked_yield(app_state)
    resp = client.post("/api/phase", json={})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_phase"


def test_api_set_phase_transition_pending(client, app_state):
    """POST /api/phase while mechanical_resume is already set returns 409."""
    from koan.lib.workflows import get_workflow

    app_state.run.workflow = get_workflow("plan")
    app_state.run.phase = "intake"
    _setup_parked_yield(app_state)
    app_state.interactions.mechanical_resume = True

    resp = client.post("/api/phase", json={"phase": "plan"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "transition_pending"


def test_api_set_workflow_unknown_workflow(client, app_state):
    """POST /api/workflow with an unknown workflow returns 422 unknown_workflow."""
    _setup_parked_yield(app_state)
    resp = client.post("/api/workflow", json={"workflow": "nonexistent"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "unknown_workflow"


def test_api_run_clear_route_deleted(client):
    """POST /api/run/clear is gone (404 or 405 -- route deleted, no POST handler)."""
    resp = client.post("/api/run/clear", json={})
    assert resp.status_code in (404, 405), f"expected 404/405, got {resp.status_code}"


def test_api_run_clear_not_importable():
    """api_run_clear is not importable from koan.web.app."""
    from koan.web import app as app_module
    assert not hasattr(app_module, "api_run_clear")
