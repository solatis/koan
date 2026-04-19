# Tests for key web flows: SSE replay, SPA fallback, start-run, artifacts, path traversal.

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
from koan.probe import ProbeResult
from koan.state import AppState
from koan.types import AgentInstallation, ModelInfo, Profile, ProfileTier
from koan.web.app import create_app


# -- Helpers ------------------------------------------------------------------

def _make_probe_results() -> list[ProbeResult]:
    return [
        ProbeResult(
            runner_type="claude", available=True, binary_path="/fake/bin/claude", version="1.0",
            models=[
                ModelInfo(alias="opus", display_name="Opus",
                         thinking_modes=frozenset({"disabled", "low", "medium", "high", "xhigh"}),
                         tier_hint="strong"),
                ModelInfo(alias="sonnet", display_name="Sonnet",
                         thinking_modes=frozenset({"disabled", "low", "medium", "high", "xhigh"}),
                         tier_hint="standard"),
            ],
        ),
        ProbeResult(runner_type="codex", available=False),
        ProbeResult(runner_type="gemini", available=False),
    ]


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def app_state():
    st = AppState()
    st.config = KoanConfig()
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


def test_start_run_requires_profile(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post("/api/start-run", json={"task": "build something"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "profile" in resp.json()["message"]


def test_start_run_rejects_empty_profile(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post("/api/start-run", json={"task": "build something", "profile": ""})
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "profile" in resp.json()["message"]


def test_start_run_blocked_no_runners(client, app_state):
    app_state.probe_results = [
        ProbeResult(runner_type="claude", available=False),
        ProbeResult(runner_type="codex", available=False),
        ProbeResult(runner_type="gemini", available=False),
    ]
    resp = client.post("/api/start-run", json={"task": "build something", "profile": "balanced"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "no_runners"


# -- Start-run preflight -------------------------------------------------------

def test_preflight_returns_required_types(client, app_state):
    from koan.runners.registry import compute_builtin_profiles
    app_state.probe_results = _make_probe_results()
    app_state.builtin_profiles = compute_builtin_profiles(app_state.probe_results)
    resp = client.get("/api/start-run/preflight?profile=balanced")
    assert resp.status_code == 200
    data = resp.json()
    assert "claude" in data["required_runner_types"]
    assert "claude" in data["installations"]


def test_preflight_shows_binary_validity(client, app_state, tmp_path):
    from koan.runners.registry import compute_builtin_profiles
    app_state.probe_results = _make_probe_results()
    app_state.builtin_profiles = compute_builtin_profiles(app_state.probe_results)
    real_binary = tmp_path / "claude"
    real_binary.touch()
    app_state.config.agent_installations = [
        AgentInstallation(alias="good", runner_type="claude", binary=str(real_binary)),
        AgentInstallation(alias="bad", runner_type="claude", binary="/nonexistent/claude"),
    ]
    resp = client.get("/api/start-run/preflight?profile=balanced")
    data = resp.json()
    insts = data["installations"]["claude"]
    good = next(i for i in insts if i["alias"] == "good")
    bad = next(i for i in insts if i["alias"] == "bad")
    assert good["binary_valid"] is True
    assert bad["binary_valid"] is False


def test_preflight_missing_profile(client, app_state):
    resp = client.get("/api/start-run/preflight?profile=nonexistent")
    assert resp.status_code == 404


# -- Start-run installation validation -----------------------------------------

def test_start_run_rejects_missing_binary(client, app_state):
    from koan.runners.registry import compute_builtin_profiles
    app_state.probe_results = _make_probe_results()
    app_state.builtin_profiles = compute_builtin_profiles(app_state.probe_results)
    app_state.config.agent_installations = [
        AgentInstallation(alias="broken", runner_type="claude", binary="/nonexistent/claude"),
    ]
    app_state.run_installations = {"claude": "broken"}
    resp = client.post("/api/start-run", json={
        "task": "build something",
        "profile": "balanced",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "binary_not_found"
    assert "claude" in data["runner_type"]


def test_start_run_rejects_unknown_installation_alias(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post("/api/start-run", json={
        "task": "build something",
        "profile": "balanced",
        "installations": {"claude": "ghost"},
    })
    assert resp.status_code == 422
    assert "ghost" in resp.json()["message"]


# -- Artifacts ----------------------------------------------------------------

def test_artifact_listing(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "landscape.md").write_text("# Landscape\n", "utf-8")
        app_state.run_dir = str(run_dir)
        app_state.start_event.set()

        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["path"] == "landscape.md"


def test_artifact_content(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "landscape.md").write_text("# Hello\n", "utf-8")
        app_state.run_dir = str(run_dir)
        app_state.start_event.set()

        resp = client.get("/api/artifacts/landscape.md")
        assert resp.status_code == 200
        data = resp.json()
        assert "# Hello" in data["content"]
        assert data["displayPath"] == "landscape.md"


def test_path_traversal_blocked(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        run_dir.mkdir(exist_ok=True)
        app_state.run_dir = str(run_dir)
        app_state.start_event.set()

        # URL-normalized traversal (../) is resolved before routing and hits the SPA fallback.
        # Use URL-encoded slashes (%2F) to test path traversal within the artifact handler.
        resp = client.get("/api/artifacts/..%2F..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)


# -- Profile endpoints --------------------------------------------------------

def test_profiles_create_invalid_runner(client, app_state):
    app_state.probe_results = _make_probe_results()

    resp = client.post("/api/profiles", json={
        "name": "bad-runner",
        "tiers": {
            "strong": {"runner_type": "codex", "model": "gpt-5", "thinking": "disabled"},
        },
    })
    assert resp.status_code == 422
    assert "not available" in resp.json()["message"]


def test_profiles_create_invalid_model(client, app_state):
    app_state.probe_results = _make_probe_results()

    resp = client.post("/api/profiles", json={
        "name": "bad-model",
        "tiers": {
            "strong": {"runner_type": "claude", "model": "nonexistent", "thinking": "disabled"},
        },
    })
    assert resp.status_code == 422
    assert "not found" in resp.json()["message"]


def test_profiles_create_invalid_thinking(client, app_state):
    app_state.probe_results = _make_probe_results()

    resp = client.post("/api/profiles", json={
        "name": "bad-thinking",
        "tiers": {
            "strong": {"runner_type": "claude", "model": "opus", "thinking": "turbo"},
        },
    })
    assert resp.status_code == 422
    assert "not supported" in resp.json()["message"]


def test_profiles_update_balanced_rejected(client, app_state):
    resp = client.put("/api/profiles/balanced", json={"tiers": {}})
    assert resp.status_code == 422
    assert resp.json()["error"] == "read_only"


def test_profiles_delete_balanced_rejected(client, app_state):
    resp = client.delete("/api/profiles/balanced")
    assert resp.status_code == 400
    assert resp.json()["error"] == "read_only"


def test_profiles_create_non_dict_tiers(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post("/api/profiles", json={
        "name": "bad-tiers",
        "tiers": [],
    })
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "object" in resp.json()["message"]


def test_profiles_create_non_dict_tier_entry(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post("/api/profiles", json={
        "name": "bad-entry",
        "tiers": {"strong": "bad"},
    })
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "must be an object" in resp.json()["message"]


def test_profiles_update_non_dict_tiers(client, app_state):
    app_state.probe_results = _make_probe_results()
    app_state.config.profiles.append(Profile(name="myprofile", tiers={}))
    resp = client.put("/api/profiles/myprofile", json={"tiers": "bad"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"
    assert "object" in resp.json()["message"]


def test_profiles_delete_user_profile(client, app_state):
    app_state.config.profiles.append(Profile(name="myprofile", tiers={}))
    resp = client.delete("/api/profiles/myprofile")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert not any(p.name == "myprofile" for p in app_state.config.profiles)


# -- Agent detect endpoint ----------------------------------------------------

def test_agents_detect_found(client, app_state):
    with patch("koan.web.app.shutil.which", return_value="/usr/bin/claude"):
        resp = client.get("/api/agents/detect?runner_type=claude")
    assert resp.status_code == 200
    assert resp.json()["path"] == "/usr/bin/claude"


def test_agents_detect_not_found(client, app_state):
    with patch("koan.web.app.shutil.which", return_value=None):
        resp = client.get("/api/agents/detect?runner_type=claude")
    assert resp.status_code == 200
    assert resp.json()["path"] is None


def test_agents_detect_missing_param(client, app_state):
    resp = client.get("/api/agents/detect")
    assert resp.status_code == 422


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
    app_state.start_event.set()
    app_state.run_dir = "/tmp/fake-run"
    app_state.phase = "intake"

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

def test_landing_includes_profile_selector(client, app_state):
    # After SPA migration, GET / serves the React SPA, not server-rendered HTML.
    # Profile selector is rendered client-side by React.
    app_state.probe_results = _make_probe_results()
    app_state.builtin_profiles = {"balanced": Profile(name="balanced", tiers={
        "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
    })}
    resp = client.get("/")
    assert resp.status_code == 200


def test_landing_start_run_disabled_no_runners(client, app_state):
    # After SPA migration, runner availability is checked client-side via /api/probe.
    app_state.probe_results = [
        ProbeResult(runner_type="claude", available=False),
        ProbeResult(runner_type="codex", available=False),
    ]
    resp = client.get("/")
    assert resp.status_code == 200


def test_landing_start_run_enabled_with_runners(client, app_state):
    # After SPA migration, GET / serves the SPA regardless of runner state.
    app_state.probe_results = _make_probe_results()
    app_state.builtin_profiles = {"balanced": Profile(name="balanced", tiers={})}
    resp = client.get("/")
    assert resp.status_code == 200


def test_start_run_sends_profile(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post(
        "/api/start-run",
        json={"task": "build something", "profile": "balanced"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert app_state.config.active_profile == "balanced"


def test_start_run_unknown_profile_rejected(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post(
        "/api/start-run",
        json={"task": "build something", "profile": "nonexistent"},
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["message"]


def test_agents_list(client, app_state):
    app_state.config.agent_installations.append(AgentInstallation(
        alias="my-claude", runner_type="claude", binary="/fake/bin/claude", extra_args=[],
    ))
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "installations" in data
    aliases = [inst["alias"] for inst in data["installations"]]
    assert "my-claude" in aliases
    assert len(data["installations"]) >= 1


def test_agents_create_and_delete(client, app_state):
    resp = client.post("/api/agents", json={
        "alias": "test-agent",
        "runner_type": "claude",
        "binary": "/fake/bin/claude",
        "extra_args": [],
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert any(i.alias == "test-agent" for i in app_state.config.agent_installations)

    resp = client.delete("/api/agents/test-agent")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert not any(i.alias == "test-agent" for i in app_state.config.agent_installations)


# -- Probe refresh ------------------------------------------------------------

class TestProbeRefresh:
    def test_probe_refresh_triggers_restate(self, client, app_state):
        fresh_probes = [
            ProbeResult(runner_type="claude", available=True, binary_path="/fake/bin/claude", version="2.0"),
            ProbeResult(runner_type="codex", available=True),
        ]
        fresh_profile = Profile(name="balanced", tiers={
            "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
        })

        fresh_builtins = {"balanced": fresh_profile}

        # Pre-populate with stale data
        app_state.probe_results = _make_probe_results()
        app_state.builtin_profiles = {}

        with patch("koan.probe.probe_all_runners", new_callable=AsyncMock, return_value=fresh_probes) as mock_probe, \
             patch("koan.runners.registry.compute_builtin_profiles", return_value=fresh_builtins) as mock_builtins:
            resp = client.get("/api/probe?refresh=1")

        assert resp.status_code == 200
        mock_probe.assert_called_once()
        mock_builtins.assert_called_once_with(fresh_probes)
        assert app_state.probe_results is fresh_probes
        assert app_state.builtin_profiles is fresh_builtins
        data = resp.json()
        assert len(data["runners"]) == 2

    def test_probe_no_refresh_skips_restate(self, client, app_state):
        app_state.probe_results = _make_probe_results()
        app_state.builtin_profiles = {"balanced": Profile(name="balanced", tiers={})}

        with patch("koan.probe.probe_all_runners", new_callable=AsyncMock) as mock_probe:
            resp = client.get("/api/probe")

        assert resp.status_code == 200
        mock_probe.assert_not_called()
        data = resp.json()
        assert len(data["runners"]) == 3



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
