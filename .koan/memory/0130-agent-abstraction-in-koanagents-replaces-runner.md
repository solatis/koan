---
title: Agent abstraction in koan/agents/ replaces Runner Protocol; ClaudeSDKAgent
  + CommandLineAgent split with PostToolUse steering hook
type: decision
created: '2026-05-02T07:23:05Z'
modified: '2026-05-02T07:23:05Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli-spawning.md
- 0016-steering-vs-phase-boundary-message-routing-dual-queue-design.md
- 0004-file-boundary-invariant-llms-write-markdown-driver-writes-json.md
---

The koan agent-spawn layer (`koan/agents/`, `koan/subagent.py:spawn_subagent`, `koan/agents/steering.py`, `koan/web/mcp_endpoint.py:_drain_and_append_steering`) was redesigned between 2026-04-29 and 2026-05-02 to integrate the Claude Agent SDK as the canonical Claude transport. On 2026-04-29, user directed the migration with the brief instruction "migrate our Claude Code agent implementation to use the Claude Agent SDK"; intake and tech-plan-spec produced a 13-decision design captured in the run brief at `~/.koan/runs/1777448300-422e9a02/brief.md`. On 2026-04-29 the agent-abstraction milestone shipped the new package with an interim `CommandLineAgent` wrapper around `ClaudeRunner`; on 2026-04-30 the SDK-adapter milestone shipped `ClaudeSDKAgent` and deleted `koan/runners/claude.py`; on 2026-05-02 the documentation milestone shipped `docs/agent-protocol.md`.

The architectural spine: user approved a new `Agent` Protocol with primitives `run`, `interrupt`, `compact`, `register_process`, `exit_code`, `stderr_output`, `list_models`, replacing the subprocess-shaped `Runner` Protocol as koan's public surface for agent integration. Two implementations satisfy the Protocol -- `ClaudeSDKAgent` (drives `claude_agent_sdk.ClaudeSDKClient`, dependency pinned in `pyproject.toml`) and `CommandLineAgent` (wraps `koan.runners.base.Runner` instances for codex and gemini); `koan/runners/` became an internal detail of `CommandLineAgent`. Configuration flowed through a single `AgentOptions` dataclass passed to `Agent.run()`. Steering migrated to a single `PostToolUse` hook on Claude calling `koan/agents/steering.py:drain_for_primary` and rendering via `render_text` for the SDK's `additionalContext` field; codex and gemini retained MCP-handler injection (`render_blocks` for content-block output). Both paths shared the single `drain_for_primary` helper -- one drain, two formatters. Hooks stayed a Claude-internal implementation detail not exposed on the Protocol.

HTTP MCP at `http://localhost:{port}/mcp?agent_id={id}` remained the single transport for all agents -- user rejected in-process `McpSdkServerConfig` for parity with codex and gemini and to preserve the existing `AgentResolutionMiddleware` agent-id-via-URL convention. User directed a hard cutover with no opt-out flag; `koan/runners/claude.py`, `RunnerDiagnostic`, and `RunnerError` were deleted in one change. `interrupt()` was defined but no caller was wired in this work; `compact()` raises `NotImplementedError` everywhere because the SDK does not expose programmatic compaction. The decision superseded part of the 2026-04-02 rationale that had rejected an "API-based" Claude integration: the Agent abstraction is API-shaped via the SDK but preserves the persistent-process model, the `StreamEvent` contract, and the per-agent runner abstraction the earlier rejection was protecting.
