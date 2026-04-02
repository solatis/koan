# CodexRunner -- builds codex CLI commands and parses --json JSONL.
# MCP injection via -c flag override (no file I/O needed).

from __future__ import annotations

import json

from ..types import AgentInstallation, ModelInfo, ThinkingMode
from .base import KOAN_MCP_TOOLS, RunnerDiagnostic, RunnerError, StreamEvent

# Canonical tool name mappings for Codex's tool vocabulary.
_TOOL_NAME_MAP: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "apply_patch": "edit",
    "shell": "bash",
    "search_files": "grep",
}


def _normalize_tool_name(name: str | None) -> str | None:
    if name is None:
        return None
    return _TOOL_NAME_MAP.get(name, name.lower())


def _extract_tool_summary(tool: str, args_str: str) -> str:
    """Extract human-readable detail from Codex tool arguments (JSON string)."""
    try:
        args = json.loads(args_str) if args_str else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    if tool == "read":
        return args.get("path", "") or args.get("file", "")
    if tool == "bash":
        return args.get("command", "") or args.get("cmd", "")
    if tool in ("write", "edit"):
        return args.get("path", "") or args.get("file", "")
    if tool == "grep":
        return args.get("pattern", "") or args.get("query", "")
    if tool == "ls":
        return args.get("path", "")
    return ""


class CodexRunner:
    name = "codex"
    supported_thinking_modes: frozenset[ThinkingMode] = frozenset({"disabled"})

    def list_models(self, binary: str) -> list[ModelInfo]:
        return [
            ModelInfo(
                alias="gpt-5", display_name="GPT-5",
                thinking_modes=frozenset({"disabled"}),
                tier_hint="strong",
            ),
            ModelInfo(
                alias="gpt-5-mini", display_name="GPT-5 Mini",
                thinking_modes=frozenset({"disabled"}),
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
        if thinking != "disabled":
            raise RunnerError(RunnerDiagnostic(
                code="unsupported_thinking_mode",
                runner="codex",
                stage="build_command",
                message=f"Thinking mode '{thinking}' is not supported by codex",
            ))

        cmd = [
            installation.binary, "exec", "--json",
            "-c", f"mcp_servers.koan.url={mcp_url}",
            boot_prompt,
        ]
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

        if evt_type == "turn.started":
            return [StreamEvent(type="thinking", is_thinking=True)]
        if evt_type == "turn.completed":
            content = data.get("answer")
            return [StreamEvent(type="turn_complete", is_thinking=True, content=content)]
        if evt_type == "turn.failed":
            return [StreamEvent(type="turn_complete", is_thinking=True)]
        if evt_type == "item.completed":
            item = data.get("item")
            if not isinstance(item, dict):
                return []
            item_type = item.get("type", "")
            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    # Codex emits complete messages (not token-by-token).
                    # Append a newline so consecutive messages don't run together
                    # in the stream buffer.
                    return [
                        StreamEvent(type="token_delta", content=text + "\n"),
                        StreamEvent(type="assistant_text", content=text),
                    ]
            elif item_type == "function_call":
                raw_name = item.get("name") or item.get("call_id", "tool")
                canonical = _normalize_tool_name(raw_name)
                if canonical in KOAN_MCP_TOOLS:
                    return []
                args_str = item.get("arguments", "")
                return [StreamEvent(
                    type="tool_call",
                    tool_name=canonical,
                    content=args_str,
                    summary=_extract_tool_summary(canonical or "", args_str),
                )]
        return []
