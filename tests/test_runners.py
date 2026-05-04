# Unit tests for koan.runners -- parse_stream_event, build_command,
# list_models, thinking modes, and extra_args.
# ClaudeRunner tests removed in M2; Claude path coverage comes from
# tests/test_subagent.py (FakeAgent) and the evals/ harness.

import json

import pytest

from koan.agents.base import AgentError
from koan.runners import CodexRunner, GeminiRunner, StreamEvent
from koan.types import AgentInstallation


def _install(name: str, extra_args: list[str] | None = None) -> AgentInstallation:
    return AgentInstallation(
        alias=name, runner_type=name, binary=name, extra_args=extra_args or []
    )


# -- CodexRunner: build_command ------------------------------------------------

class TestCodexRunnerBuildCommand:
    def test_command_contains_mcp_override(self):
        runner = CodexRunner()
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("codex"), "gpt-5", "disabled",
        )
        assert "-c" in cmd
        idx = cmd.index("-c")
        assert cmd[idx + 1] == "mcp_servers.koan.url=http://localhost:9000/mcp"
        assert cmd[0] == "codex"


# -- GeminiRunner: build_command -----------------------------------------------

class TestGeminiRunnerBuildCommand:
    def test_writes_settings_json(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "do stuff", "http://localhost:9000/mcp",
            _install("gemini"), "gemini-pro", "disabled",
        )

        settings = tmp_path / ".gemini" / "settings.json"
        assert settings.exists()
        written = json.loads(settings.read_text("utf-8"))
        assert written["mcpServers"]["koan"]["httpUrl"] == "http://localhost:9000/mcp"

        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert cmd[0] == "gemini"

    def test_merge_conflict_raises_agent_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({
            "mcpServers": {"koan": {"httpUrl": "http://other:1234/mcp"}},
        }))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        assert exc_info.value.diagnostic.code == "mcp_inject_failed"

    def test_non_object_toplevel_raises_agent_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps([1, 2, 3]))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert diag.agent == "gemini"
        assert "list" in diag.message

    def test_non_dict_mcp_servers_raises_agent_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": "not-a-dict"}))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert "mcpServers" in diag.message

    def test_non_dict_koan_entry_raises_agent_error(self, tmp_path):
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings = gemini_dir / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"koan": "a-string"}}))

        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "do stuff", "http://localhost:9000/mcp",
                _install("gemini"), "gemini-pro", "disabled",
            )
        diag = exc_info.value.diagnostic
        assert diag.code == "mcp_inject_failed"
        assert "mcpServers.koan" in diag.message


# -- CodexRunner: thinking modes -----------------------------------------------

class TestCodexRunnerThinkingMode:
    def test_disabled_succeeds(self):
        runner = CodexRunner()
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("codex"), "gpt-5", "disabled",
        )
        assert "codex" == cmd[0]

    def test_low_raises_agent_error(self):
        runner = CodexRunner()
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "p", "http://x/mcp", _install("codex"), "gpt-5", "low",
            )
        assert exc_info.value.diagnostic.code == "unsupported_thinking_mode"


# -- CodexRunner: list_models --------------------------------------------------

class TestCodexRunnerListModels:
    def test_returns_two_models(self):
        runner = CodexRunner()
        models = runner.list_models("codex")
        assert len(models) == 2

    def test_both_disabled_only(self):
        runner = CodexRunner()
        for m in runner.list_models("codex"):
            assert m.thinking_modes == frozenset({"disabled"})


# -- CodexRunner: extra_args ---------------------------------------------------

class TestCodexRunnerExtraArgs:
    def test_extra_args_at_end(self):
        runner = CodexRunner()
        inst = AgentInstallation(
            alias="codex", runner_type="codex", binary="codex",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "gpt-5", "disabled")
        assert cmd[-1] == "--verbose"


# -- GeminiRunner: thinking modes ----------------------------------------------

class TestGeminiRunnerThinkingMode:
    def test_disabled_no_thinking_flag(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "disabled",
        )
        assert "--thinking-mode" not in cmd

    def test_low_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "low",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "low"

    def test_medium_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "medium",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "medium"

    def test_high_thinking(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        cmd = runner.build_command(
            "p", "http://x/mcp", _install("gemini"), "gemini-pro", "high",
        )
        idx = cmd.index("--thinking-mode")
        assert cmd[idx + 1] == "high"

    def test_xhigh_raises_agent_error(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        with pytest.raises(AgentError) as exc_info:
            runner.build_command(
                "p", "http://x/mcp", _install("gemini"), "gemini-pro", "xhigh",
            )
        assert exc_info.value.diagnostic.code == "unsupported_thinking_mode"


# -- GeminiRunner: list_models -------------------------------------------------

class TestGeminiRunnerListModels:
    def test_returns_two_models(self):
        runner = GeminiRunner(subagent_dir="/tmp/x")
        models = runner.list_models("gemini")
        assert len(models) == 2

    def test_flash_limited_thinking(self):
        runner = GeminiRunner(subagent_dir="/tmp/x")
        models = runner.list_models("gemini")
        flash = [m for m in models if m.alias == "gemini-flash"][0]
        assert flash.thinking_modes == frozenset({"disabled", "low"})


# -- GeminiRunner: extra_args --------------------------------------------------

class TestGeminiRunnerExtraArgs:
    def test_extra_args_at_end(self, tmp_path):
        runner = GeminiRunner(subagent_dir=str(tmp_path))
        inst = AgentInstallation(
            alias="gemini", runner_type="gemini", binary="gemini",
            extra_args=["--verbose"],
        )
        cmd = runner.build_command("p", "http://x/mcp", inst, "gemini-pro", "disabled")
        assert cmd[-1] == "--verbose"


# -- CodexRunner: tool args ----------------------------------------------------

class TestCodexToolArgs:
    """Codex runner synthesizes three-event sequence; args arrive on tool_input_delta."""
    def setup_method(self):
        self.runner = CodexRunner()

    def _item(self, name, args_dict):
        import json
        return json.dumps({"type": "item.completed", "item": {
            "type": "function_call", "name": name, "arguments": json.dumps(args_dict)
        }})

    def _delta_args(self, evts) -> dict:
        for ev in evts:
            if ev.type == "tool_input_delta":
                return ev.tool_args or {}
        raise AssertionError("no tool_input_delta event")

    def test_read_args(self):
        line = self._item("read_file", {"path": "/src/foo.ts"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["path"] == "/src/foo.ts"

    def test_bash_args(self):
        line = self._item("shell", {"command": "npm test"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["command"] == "npm test"

    def test_write_args(self):
        line = self._item("write_file", {"path": "/out/result.ts"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["path"] == "/out/result.ts"

    def test_three_events_emitted(self):
        line = self._item("shell", {"command": "ls"})
        evts = self.runner.parse_stream_event(line)
        types = [e.type for e in evts]
        assert types == ["tool_start", "tool_input_delta", "tool_result"]

    def test_no_function_call_output_event(self):
        """function_call_output should not produce any events."""
        import json
        line = json.dumps({"type": "item.completed", "item": {
            "type": "function_call_output", "output": "some result"
        }})
        evts = self.runner.parse_stream_event(line)
        assert evts == []


# -- GeminiRunner: tool args ---------------------------------------------------

class TestGeminiToolArgs:
    """Gemini runner synthesizes three-event sequence; args arrive on tool_input_delta."""
    def setup_method(self):
        self.runner = GeminiRunner(subagent_dir="/tmp/test-gemini")

    def _tool(self, name, input_dict):
        import json
        return json.dumps({"type": "tool_use", "name": name, "input": input_dict})

    def _delta_args(self, evts) -> dict:
        for ev in evts:
            if ev.type == "tool_input_delta":
                return ev.tool_args or {}
        raise AssertionError("no tool_input_delta event")

    def test_read_args(self):
        line = self._tool("read_file", {"file_path": "/src/bar.go"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["file_path"] == "/src/bar.go"

    def test_bash_args(self):
        line = self._tool("run_bash_command", {"command": "go build"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["command"] == "go build"

    def test_ls_args(self):
        line = self._tool("list_directory", {"path": "/src"})
        evts = self.runner.parse_stream_event(line)
        assert self._delta_args(evts)["path"] == "/src"

    def test_three_events_emitted(self):
        line = self._tool("run_bash_command", {"command": "ls"})
        evts = self.runner.parse_stream_event(line)
        types = [e.type for e in evts]
        assert types == ["tool_start", "tool_input_delta", "tool_result"]
