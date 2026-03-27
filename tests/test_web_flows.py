# Tests for key web flows: SSE replay, landing page, start-run, artifacts, path traversal.

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


# -- Landing page -------------------------------------------------------------

def test_landing_page_renders(client, app_state):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "task-input" in resp.text
    assert "Start Run" in resp.text


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

        resp = client.get("/api/artifacts/../../../etc/passwd")
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

    app_state.last_sse_values["phase"] = {"phase": "intake", "html": "<div>test</div>", "target": "status-sidebar"}

    # Verify the SSE event formatter produces correct output
    event_str = _sse_event("phase", app_state.last_sse_values["phase"])
    assert "event: phase" in event_str
    assert '"intake"' in event_str

    # Verify replay cache is populated
    assert "phase" in app_state.last_sse_values
    assert app_state.last_sse_values["phase"]["phase"] == "intake"


# -- Live page redirect -------------------------------------------------------

def test_live_page_when_running(client, app_state):
    app_state.start_event.set()
    app_state.epic_dir = "/tmp/fake-epic"
    app_state.phase = "intake"

    resp = client.get("/")
    assert resp.status_code == 200
    assert "pill-strip" in resp.text
    assert "activity-feed-inner" in resp.text


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

    payload = app_state.last_sse_values["interaction"]
    assert "html" in payload
    assert payload["target"] == "workspace-main-content"
    assert "workflow-option" in payload["html"]
    assert 'data-phase="tech-plan"' in payload["html"]


# -- Old model-config route removed ------------------------------------------

def test_model_config_removed(client, app_state):
    resp = client.get("/api/model-config")
    assert resp.status_code in (404, 405)
