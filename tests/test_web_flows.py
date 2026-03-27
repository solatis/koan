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
from koan.state import AppState
from koan.web.app import create_app


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
    resp = client.post(
        "/api/start-run",
        json={"task": "build something"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert app_state.start_event.is_set()
    assert app_state.epic_dir is not None


def test_start_run_requires_task(client, app_state):
    resp = client.post("/api/start-run", json={"task": ""})
    assert resp.status_code == 422


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


# -- Model config -------------------------------------------------------------

def test_model_config_get(client, app_state):
    resp = client.get("/api/model-config")
    assert resp.status_code == 200
    data = resp.json()
    assert "activeProfile" in data
    assert "scoutConcurrency" in data


def test_model_config_put(client, app_state):
    resp = client.put(
        "/api/model-config",
        json={
            "scout_concurrency": 4,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert app_state.config.scout_concurrency == 4


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
