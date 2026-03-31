# ClaudeRunner -- builds claude CLI commands and parses stream-json JSONL.
# MCP injection via --mcp-config file written to the subagent directory.

from __future__ import annotations

import json
from pathlib import Path

from ..types import AgentInstallation, ModelInfo, ThinkingMode
from .base import KOAN_MCP_TOOLS, RunnerDiagnostic, RunnerError, StreamEvent

# Map internal thinking mode names to Claude CLI --effort values.
_EFFORT_MAP: dict[ThinkingMode, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",  # opus only
}

# Canonical tool name mappings for Claude's tool vocabulary.
_TOOL_NAME_MAP: dict[str, str] = {
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Bash": "bash",
    "Glob": "grep",
    "Grep": "grep",
    "LS": "ls",
    "TodoRead": "todo_read",
    "TodoWrite": "todo_write",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
}


def _normalize_tool_name(name: str | None) -> str | None:
    if name is None:
        return None
    return _TOOL_NAME_MAP.get(name, name.lower())


class ClaudeRunner:
    name = "claude"
    supported_thinking_modes: frozenset[ThinkingMode] = frozenset(
        {"disabled", "low", "medium", "high", "xhigh"}
    )

    def __init__(self, *, subagent_dir: str) -> None:
        self.subagent_dir = subagent_dir

    def list_models(self, binary: str) -> list[ModelInfo]:
        return [
            ModelInfo(
                alias="opus", display_name="Opus",
                thinking_modes=frozenset({"disabled", "low", "medium", "high", "xhigh"}),
                tier_hint="strong",
            ),
            ModelInfo(
                alias="sonnet", display_name="Sonnet",
                thinking_modes=frozenset({"disabled", "low", "medium", "high"}),
                tier_hint="standard",
            ),
            ModelInfo(
                alias="haiku", display_name="Haiku",
                thinking_modes=frozenset({"disabled", "low"}),
                tier_hint="cheap",
            ),
        ]

    def build_command(
        self,
        boot_prompt: str,
        mcp_url: str,
        installation: AgentInstallation,
        model: str,
        thinking: ThinkingMode,
    ) -> list[str]:
        if thinking not in self.supported_thinking_modes:
            raise RunnerError(RunnerDiagnostic(
                code="unsupported_thinking_mode",
                runner="claude",
                stage="build_command",
                message=f"Thinking mode '{thinking}' is not supported by claude",
            ))

        config_dir = Path(self.subagent_dir)
        config_path = config_dir / "mcp-config.json"
        config_data = {"mcpServers": {"koan": {"type": "http", "url": mcp_url}}}

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            tmp = config_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(config_data, indent=2) + "\n", "utf-8")
            tmp.rename(config_path)
        except OSError as e:
            raise RunnerError(RunnerDiagnostic(
                code="mcp_inject_failed",
                runner="claude",
                stage="build_command",
                message=f"Failed to write MCP config: {e}",
            )) from e

        cmd = [
            installation.binary, "-p", boot_prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--mcp-config", str(config_path),
        ]
        if thinking != "disabled":
            cmd.extend(["--effort", _EFFORT_MAP[thinking]])
        cmd.extend(["--model", model])
        cmd.extend(installation.extra_args)
        return cmd

    def parse_stream_event(self, line: str) -> list[StreamEvent]:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []

        if not isinstance(data, dict):
            return []

        evt_type = data.get("type")

        if evt_type == "assistant":
            return self._parse_assistant(data)
        if evt_type == "result":
            evt = self._parse_result(data)
            return [evt] if evt is not None else []
        return []

    # -- Private helpers -------------------------------------------------------

    def _parse_assistant(self, data: dict) -> list[StreamEvent]:
        blocks = data.get("content")
        if not isinstance(blocks, list) or len(blocks) == 0:
            return []

        events: list[StreamEvent] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                events.append(StreamEvent(type="token_delta", content=block.get("text", "")))
            elif block_type == "tool_use":
                raw_name = block.get("name")
                canonical = _normalize_tool_name(raw_name)
                # Drop koan MCP tool events -- the MCP endpoint is authoritative
                if canonical in KOAN_MCP_TOOLS:
                    continue
                events.append(StreamEvent(
                    type="tool_call",
                    tool_name=canonical,
                    tool_args=block.get("input"),
                ))
            elif block_type == "thinking":
                # Claude stream-json thinking blocks use the "thinking" key for content,
                # not "text" (which is used by text blocks). Fall back to "text" as a
                # safety net for format variations.
                events.append(StreamEvent(
                    type="thinking",
                    is_thinking=True,
                    content=block.get("thinking") or block.get("text"),
                ))
        return events

    def _parse_result(self, data: dict) -> StreamEvent | None:
        subtype = data.get("subtype")
        if subtype == "success":
            return StreamEvent(type="turn_complete", content=data.get("result"))
        return StreamEvent(type="turn_complete")
