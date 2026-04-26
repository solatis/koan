# Tests for the upload endpoint and storage primitives.
# Mirrors the style of tests/test_web_flows.py: TestClient fixtures,
# driver_main patched out, no reliance on a built frontend.

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from koan.config import KoanConfig
from koan.state import AppState, UploadState
from koan.web.app import create_app
from koan.web.uploads import (
    commit_to_run,
    init_upload_state,
    register_upload,
    shutdown_upload_state,
)


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def app_state():
    st = AppState()
    st.runner_config.config = KoanConfig()
    return st


@pytest.fixture
def client(app_state):
    with patch("koan.driver.driver_main", new_callable=AsyncMock):
        app = create_app(app_state)
        with TestClient(app) as c:
            yield c


# -- Upload endpoint tests ----------------------------------------------------

def test_upload_returns_id_and_metadata(client, app_state):
    content = b"hello upload"
    resp = client.post(
        "/api/upload",
        files={"file": ("hello.txt", io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"id", "filename", "size", "content_type"}
    assert data["filename"] == "hello.txt"
    assert data["size"] == len(content)
    assert data["content_type"] == "text/plain"
    # id must be 32 lowercase hex chars
    assert len(data["id"]) == 32
    assert all(c in "0123456789abcdef" for c in data["id"])


def test_upload_rejects_non_multipart(client):
    resp = client.post("/api/upload", json={"file": "not a file"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_multipart"


def test_upload_rejects_missing_file_field(client):
    # Correct multipart encoding but wrong field name.
    resp = client.post(
        "/api/upload",
        files={"attachment": ("hello.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "missing_file"


def test_upload_persists_to_tempdir(client, app_state):
    content = b"persistent content"
    resp = client.post(
        "/api/upload",
        files={"file": ("persist.txt", io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200
    upload_id = resp.json()["id"]

    record = app_state.uploads.entries[upload_id]
    assert record.path.exists()
    assert record.path.read_bytes() == content


def test_upload_sanitizes_filename(client, app_state):
    # Path-traversal attempt in the multipart filename header.
    content = b"should be safe"
    resp = client.post(
        "/api/upload",
        files={"file": ("../../etc/passwd", io.BytesIO(content), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Filename returned to the client is basename only.
    assert data["filename"] == "passwd"

    record = app_state.uploads.entries[data["id"]]
    # File must live strictly under the tempdir, not outside it.
    tempdir = Path(app_state.uploads.tempdir.name)
    assert record.path.is_relative_to(tempdir)
    assert record.path.name == "passwd"


# -- commit_to_run tests (exercise the function directly) ---------------------

class _FakeUploadFile:
    """Minimal duck-type of Starlette UploadFile for unit tests."""

    def __init__(self, filename: str, content: bytes, content_type: str = "application/octet-stream"):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(content)


@pytest.mark.anyio
async def test_commit_to_run_moves_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        state = UploadState()
        state.tempdir = _DummyTempDir(tmpdir)

        # Register two uploads directly.
        f1 = _FakeUploadFile("alpha.txt", b"aaa")
        f2 = _FakeUploadFile("beta.txt", b"bbb")
        r1 = await register_upload(state, f1)
        r2 = await register_upload(state, f2)

        with tempfile.TemporaryDirectory() as run_dir:
            result = commit_to_run(state, [r1.id, r2.id], run_dir)

            assert set(result.keys()) == {r1.id, r2.id}

            # Files now live under run_dir.
            for uid, path in result.items():
                assert path.exists()
                assert str(run_dir) in str(path)

            # Records updated in place.
            assert state.entries[r1.id].committed is True
            assert state.entries[r2.id].committed is True

            # Original tempdir per-id dirs removed.
            src_dir_1 = Path(tmpdir) / r1.id
            src_dir_2 = Path(tmpdir) / r2.id
            assert not src_dir_1.exists()
            assert not src_dir_2.exists()


@pytest.mark.anyio
async def test_commit_to_run_skips_unknown_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        state = UploadState()
        state.tempdir = _DummyTempDir(tmpdir)

        f1 = _FakeUploadFile("real.txt", b"real content")
        r1 = await register_upload(state, f1)

        with tempfile.TemporaryDirectory() as run_dir:
            # Mix a real id with a made-up one.
            result = commit_to_run(state, [r1.id, "deadbeef" * 4], run_dir)

            # Only the real id is in the result; the call must not raise.
            assert list(result.keys()) == [r1.id]
            assert state.entries[r1.id].committed is True


# -- Helper -------------------------------------------------------------------

class _DummyTempDir:
    """Minimal stand-in for tempfile.TemporaryDirectory used in direct tests.

    register_upload reads .name; we supply the already-created tmpdir path so
    the test controls cleanup via the outer TemporaryDirectory context manager.
    """

    def __init__(self, path: str) -> None:
        self.name = path
