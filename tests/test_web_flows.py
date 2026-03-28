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
            runner_type="claude", available=True, binary_path="/usr/bin/claude", version="1.0",
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

def test_start_run_sets_event(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post(
        "/api/start-run",
        json={"task": "build something", "profile": "balanced"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert app_state.start_event.is_set()
    assert app_state.epic_dir is not None


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


def test_start_run_persists_profile(client, app_state):
    app_state.probe_results = _make_probe_results()
    resp = client.post(
        "/api/start-run",
        json={"task": "build something", "profile": "balanced"},
    )
    assert resp.status_code == 200
    assert app_state.config.active_profile == "balanced"


# -- Artifacts ----------------------------------------------------------------

def test_artifact_listing(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        epic = Path(tmp)
        (epic / "landscape.md").write_text("# Landscape\n", "utf-8")
        app_state.epic_dir = str(epic)
        app_state.start_event.set()

        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["path"] == "landscape.md"


def test_artifact_content(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        epic = Path(tmp)
        (epic / "landscape.md").write_text("# Hello\n", "utf-8")
        app_state.epic_dir = str(epic)
        app_state.start_event.set()

        resp = client.get("/api/artifacts/landscape.md")
        assert resp.status_code == 200
        data = resp.json()
        assert "# Hello" in data["content"]
        assert data["displayPath"] == "landscape.md"


def test_path_traversal_blocked(client, app_state):
    with tempfile.TemporaryDirectory() as tmp:
        epic = Path(tmp)
        epic.mkdir(exist_ok=True)
        app_state.epic_dir = str(epic)
        app_state.start_event.set()

        # URL-normalized traversal (../) is resolved before routing and hits the SPA fallback.
        # Use URL-encoded slashes (%2F) to test path traversal within the artifact handler.
        resp = client.get("/api/artifacts/..%2F..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)


# -- Probe endpoint -----------------------------------------------------------

def test_probe_endpoint(client, app_state):
    app_state.probe_results = _make_probe_results()
    app_state.balanced_profile = Profile(name="balanced", tiers={
        "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
    })

    resp = client.get("/api/probe")
    assert resp.status_code == 200
    data = resp.json()
    assert "runners" in data
    assert "balanced_profile" in data
    assert len(data["runners"]) == 3
    assert data["runners"][0]["runner_type"] == "claude"
    assert len(data["runners"][0]["models"]) == 2


# -- Profile endpoints --------------------------------------------------------

def test_profiles_list_includes_balanced(client, app_state):
    app_state.balanced_profile = Profile(name="balanced", tiers={
        "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
    })

    resp = client.get("/api/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["name"] == "balanced" and p["read_only"] is True for p in data["profiles"])


def test_profiles_create_valid(client, app_state):
    app_state.probe_results = _make_probe_results()

    resp = client.post("/api/profiles", json={
        "name": "myprofile",
        "tiers": {
            "strong": {"runner_type": "claude", "model": "opus", "thinking": "high"},
        },
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert any(p.name == "myprofile" for p in app_state.config.profiles)


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
    """Test that SSE stream replays last_sse_values on connect."""
    from koan.web.app import _sse_event
    from koan.driver import push_sse

    # Push a phase event through the new JSON-only push_sse
    push_sse(app_state, "phase", "intake")

    # Verify the replay cache now holds the JSON payload (no html/target)
    assert "phase" in app_state.last_sse_values
    payload = app_state.last_sse_values["phase"]
    assert payload["phase"] == "intake"
    assert "html" not in payload
    assert "target" not in payload

    # Verify the SSE event formatter produces correct output
    event_str = _sse_event("phase", payload)
    assert "event: phase" in event_str
    assert '"intake"' in event_str


# -- Live page redirect (now SPA fallback) ------------------------------------

def test_live_page_when_running(client, app_state):
    # After SPA migration, GET / always returns the SPA entry point.
    # The React app reads store state client-side to render the live view.
    app_state.start_event.set()
    app_state.epic_dir = "/tmp/fake-epic"
    app_state.phase = "intake"

    resp = client.get("/")
    assert resp.status_code == 200
    assert "root" in resp.text


# -- Workflow interaction SSE payload -----------------------------------------

def test_workflow_interaction_sse_payload_shape(app_state):
    from koan.driver import push_sse

    push_sse(app_state, "interaction", {
        "type": "workflow-decision",
        "token": "tok",
        "chat_turns": [{
            "role": "orchestrator",
            "status_report": "Done",
            "recommended_phases": [{
                "phase": "tech-plan",
                "context": "next",
                "recommended": True,
            }],
        }],
    })

    # After SPA migration, interaction payloads are pure JSON (no html/target).
    payload = app_state.last_sse_values["interaction"]
    assert payload["type"] == "workflow-decision"
    assert payload["token"] == "tok"
    assert "html" not in payload
    assert "target" not in payload
    # Verify the phase data is in the payload
    turns = payload["chat_turns"]
    assert turns[0]["recommended_phases"][0]["phase"] == "tech-plan"


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
    app_state.balanced_profile = Profile(name="balanced", tiers={
        "strong": ProfileTier(runner_type="claude", model="opus", thinking="high"),
    })
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
    app_state.balanced_profile = Profile(name="balanced", tiers={})
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
        alias="my-claude", runner_type="claude", binary="/usr/bin/claude", extra_args=[],
    ))
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "installations" in data
    assert "active_installations" in data
    aliases = [inst["alias"] for inst in data["installations"]]
    assert "my-claude" in aliases
    assert len(data["installations"]) >= 1


def test_agents_create_and_delete(client, app_state):
    resp = client.post("/api/agents", json={
        "alias": "test-agent",
        "runner_type": "claude",
        "binary": "/usr/bin/claude",
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
            ProbeResult(runner_type="claude", available=True, binary_path="/usr/bin/claude", version="2.0"),
            ProbeResult(runner_type="codex", available=True),
        ]
        fresh_profile = Profile(name="balanced", tiers={
            "strong": ProfileTier(runner_type="codex", model="gpt-5", thinking="high"),
        })

        # Pre-populate with stale data
        app_state.probe_results = _make_probe_results()
        app_state.balanced_profile = None

        with patch("koan.probe.probe_all_runners", new_callable=AsyncMock, return_value=fresh_probes) as mock_probe, \
             patch("koan.runners.registry.compute_balanced_profile", return_value=fresh_profile) as mock_balanced:
            resp = client.get("/api/probe?refresh=1")

        assert resp.status_code == 200
        mock_probe.assert_called_once()
        mock_balanced.assert_called_once_with(fresh_probes)
        assert app_state.probe_results is fresh_probes
        assert app_state.balanced_profile is fresh_profile
        data = resp.json()
        assert len(data["runners"]) == 2

    def test_probe_no_refresh_skips_restate(self, client, app_state):
        app_state.probe_results = _make_probe_results()
        app_state.balanced_profile = Profile(name="balanced", tiers={})

        with patch("koan.probe.probe_all_runners", new_callable=AsyncMock) as mock_probe:
            resp = client.get("/api/probe")

        assert resp.status_code == 200
        mock_probe.assert_not_called()
        data = resp.json()
        assert len(data["runners"]) == 3


def test_agents_set_active(client, app_state):
    app_state.config.agent_installations.append(AgentInstallation(
        alias="my-claude", runner_type="claude", binary="/usr/bin/claude", extra_args=[],
    ))
    resp = client.put("/api/agents/claude/active", json={"alias": "my-claude"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert app_state.config.active_installations.get("claude") == "my-claude"
