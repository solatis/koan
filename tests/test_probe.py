# Unit tests for koan.probe -- runner availability probing.

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from koan.probe import ProbeResult, _probe_claude, _probe_codex, _probe_gemini, probe_all_runners


# -- Claude probe --------------------------------------------------------------

class TestProbeClaudeBinaryNotFound:
    @pytest.mark.anyio
    async def test_returns_unavailable(self):
        with patch("koan.probe.shutil.which", return_value=None):
            r = await _probe_claude()
        assert r.available is False
        assert r.binary_path is None
        assert r.runner_type == "claude"


class TestProbeClaudeAuthFailure:
    @pytest.mark.anyio
    async def test_bad_exit_code(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(1, "", "")):
            r = await _probe_claude()
        assert r.available is False
        assert r.binary_path == "/fake/bin/claude"

    @pytest.mark.anyio
    async def test_bad_json(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(0, "not json", "")):
            r = await _probe_claude()
        assert r.available is False

    @pytest.mark.anyio
    async def test_not_logged_in(self):
        body = json.dumps({"loggedIn": False})
        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(0, body, "")):
            r = await _probe_claude()
        assert r.available is False


class TestProbeClaudeTimeout:
    @pytest.mark.anyio
    async def test_auth_timeout(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(-1, "", "")):
            r = await _probe_claude()
        assert r.available is False


class TestProbeClaudeSuccess:
    @pytest.mark.anyio
    async def test_full_probe(self):
        auth_body = json.dumps({"loggedIn": True})

        async def fake_run_cmd(args):
            if "auth" in args:
                return (0, auth_body, "")
            if "--version" in args:
                return (0, "claude 1.2.3\n", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_claude()
        assert r.available is True
        assert r.binary_path == "/fake/bin/claude"
        assert r.version == "claude 1.2.3"


class TestProbeClaudeSDKUnavailable:
    """_probe_claude returns unavailable when claude_agent_sdk is not importable.

    The SDK is required for ClaudeSDKAgent; a working CLI binary alone is not
    sufficient after the M2 cutover.
    """
    @pytest.mark.anyio
    async def test_sdk_import_error_returns_unavailable(self, monkeypatch):
        import sys
        auth_body = __import__("json").dumps({"loggedIn": True})

        async def fake_run_cmd(args):
            if "auth" in args:
                return (0, auth_body, "")
            if "--version" in args:
                return (0, "claude 1.2.3\n", "")
            return (-1, "", "")

        # Simulate missing SDK by putting None in sys.modules. Python raises
        # ImportError when a module mapping is None, regardless of the real
        # install state.
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_claude()
        assert r.available is False
        assert r.binary_path == "/fake/bin/claude"


class TestProbeClaudeVersionFailure:
    @pytest.mark.anyio
    async def test_version_nonzero_returns_unavailable(self):
        auth_body = json.dumps({"loggedIn": True})

        async def fake_run_cmd(args):
            if "auth" in args:
                return (0, auth_body, "")
            if "--version" in args:
                return (1, "", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_claude()
        assert r.available is False
        assert r.binary_path == "/fake/bin/claude"
        assert r.version is None

    @pytest.mark.anyio
    async def test_version_timeout_returns_unavailable(self):
        auth_body = json.dumps({"loggedIn": True})

        async def fake_run_cmd(args):
            if "auth" in args:
                return (0, auth_body, "")
            if "--version" in args:
                return (-1, "", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/claude"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_claude()
        assert r.available is False
        assert r.binary_path == "/fake/bin/claude"


# -- Codex probe ---------------------------------------------------------------

class TestProbeCodexBinaryNotFound:
    @pytest.mark.anyio
    async def test_returns_unavailable(self):
        with patch("koan.probe.shutil.which", return_value=None):
            r = await _probe_codex()
        assert r.available is False
        assert r.binary_path is None
        assert r.runner_type == "codex"


class TestProbeCodexAuthFailure:
    @pytest.mark.anyio
    async def test_bad_exit_code(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(1, "", "")):
            r = await _probe_codex()
        assert r.available is False

    @pytest.mark.anyio
    async def test_no_logged_in_string(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(0, "Not authenticated", "")):
            r = await _probe_codex()
        assert r.available is False


class TestProbeCodexTimeout:
    @pytest.mark.anyio
    async def test_auth_timeout(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(-1, "", "")):
            r = await _probe_codex()
        assert r.available is False


class TestProbeCodexSuccess:
    @pytest.mark.anyio
    async def test_full_probe(self):
        """Codex outputs 'Logged in' to stderr, not stdout."""
        async def fake_run_cmd(args):
            if "login" in args:
                return (0, "", "Logged in as user@example.com")
            if "--version" in args:
                return (0, "codex 0.5.1\n", "")
            return (-1, "", "")

    @pytest.mark.anyio
    async def test_logged_in_on_stdout(self):
        """Also accept 'Logged in' on stdout (future-proofing)."""
        async def fake_run_cmd(args):
            if "login" in args:
                return (0, "Logged in as user@example.com", "")
            if "--version" in args:
                return (0, "codex 0.5.1\n", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_codex()
        assert r.available is True

        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_codex()
        assert r.available is True
        assert r.binary_path == "/fake/bin/codex"
        assert r.version == "codex 0.5.1"


class TestProbeCodexVersionFailure:
    @pytest.mark.anyio
    async def test_version_nonzero_returns_unavailable(self):
        async def fake_run_cmd(args):
            if "login" in args:
                return (0, "", "Logged in as user@example.com")
            if "--version" in args:
                return (1, "", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_codex()
        assert r.available is False
        assert r.binary_path == "/fake/bin/codex"
        assert r.version is None

    @pytest.mark.anyio
    async def test_version_timeout_returns_unavailable(self):
        async def fake_run_cmd(args):
            if "login" in args:
                return (0, "", "Logged in as user@example.com")
            if "--version" in args:
                return (-1, "", "")
            return (-1, "", "")

        with patch("koan.probe.shutil.which", return_value="/fake/bin/codex"), \
             patch("koan.probe._run_cmd", side_effect=fake_run_cmd):
            r = await _probe_codex()
        assert r.available is False
        assert r.binary_path == "/fake/bin/codex"


# -- Gemini probe --------------------------------------------------------------

class TestProbeGeminiBinaryNotFound:
    @pytest.mark.anyio
    async def test_returns_unavailable(self):
        with patch("koan.probe.shutil.which", return_value=None):
            r = await _probe_gemini()
        assert r.available is False
        assert r.binary_path is None
        assert r.runner_type == "gemini"


class TestProbeGeminiAuthFailure:
    @pytest.mark.anyio
    async def test_bad_exit_code(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/gemini"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(1, "", "")):
            r = await _probe_gemini()
        assert r.available is False


class TestProbeGeminiTimeout:
    @pytest.mark.anyio
    async def test_version_timeout(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/gemini"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(-1, "", "")):
            r = await _probe_gemini()
        assert r.available is False


class TestProbeGeminiSuccess:
    @pytest.mark.anyio
    async def test_full_probe(self):
        with patch("koan.probe.shutil.which", return_value="/fake/bin/gemini"), \
             patch("koan.probe._run_cmd", new_callable=AsyncMock, return_value=(0, "gemini 2.0.0\n", "")):
            r = await _probe_gemini()
        assert r.available is True
        assert r.binary_path == "/fake/bin/gemini"
        assert r.version == "gemini 2.0.0"


# -- probe_all_runners ---------------------------------------------------------

class TestProbeAllRunners:
    @pytest.mark.anyio
    async def test_returns_three_results(self):
        with patch("koan.probe.shutil.which", return_value=None):
            results = await probe_all_runners()
        assert len(results) == 3
        assert all(isinstance(r, ProbeResult) for r in results)
        types = {r.runner_type for r in results}
        assert types == {"claude", "codex", "gemini"}

    @pytest.mark.anyio
    async def test_no_exception_on_all_failures(self):
        with patch("koan.probe.shutil.which", return_value=None):
            results = await probe_all_runners()
        assert all(r.available is False for r in results)
