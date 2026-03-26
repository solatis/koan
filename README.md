# Koan

Koan is a deterministic planning pipeline that takes a conversation describing a
coding task and produces working code -- through a structured sequence of
isolated LLM subagents, each with a narrow, auditable responsibility.

## Setup

```bash
uv sync
uv run koan
```

## How it works

```
Conversation
  -> Intake (confidence-gated investigation loop)
  -> Brief generation (distill landscape into product brief)
  -> Core flows (user journeys, sequence diagrams)
  -> Tech plan (technical architecture)
  -> Ticket breakdown (story-sized implementation tickets)
  -> Cross-artifact validation (consistency check)
  -> Execution (implement tickets)
  -> Implementation validation (post-execution review)
  -> Done
```

A single Python process (`koan/driver.py`) runs a Starlette HTTP server that
hosts both the web dashboard and an MCP tool endpoint. Subagents are CLI
processes (`claude`, `codex`, or `gemini`) that connect to
`http://localhost:{port}/mcp?agent_id={id}` to receive step guidance and call
koan tools. The driver reads JSON state and exit codes; it never parses LLM
output.

## Phases

| Phase            | Role           | What it does                                                                                                             |
| ---------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Intake**       | `intake`       | Reads the conversation, scouts the codebase, asks clarifying questions. Iterates until confident. Writes `landscape.md`. |
| **Scout**        | `scout`        | Narrow codebase investigator. Spawned in parallel by intake, decomposer, and planner via `koan_request_scouts`.          |
| **Brief writer** | `brief-writer` | Distills `landscape.md` into `brief.md`. User reviews via artifact review.                                               |
| **Orchestrator** | `orchestrator` | Selects the next story, verifies execution results, routes to retry/done/next.                                           |
| **Planner**      | `planner`      | Reads a story sketch, writes a step-by-step implementation plan and code context file.                                   |
| **Executor**     | `executor`     | Follows the plan, modifies the codebase, reports what changed.                                                           |

## Web Dashboard

Koan serves a local web dashboard at `http://localhost:{port}` during pipeline
execution. The dashboard provides:

- **Activity feed** -- real-time tool calls, scout dispatches, thinking traces
- **Agent monitor** -- status, token counts, and recent actions for each
  running subagent
- **User interaction** -- question forms (intake clarifications), review gates
  (story approval), model configuration

The dashboard uses Server-Sent Events for real-time updates. SSE events are
pushed directly from in-process state transitions and tool handlers.

## Key Concepts

**Step-first workflow.** Every subagent's first action is calling
`koan_complete_step`. This forces a tool call before any text output. Task
instructions are delivered as the return value of that first call.

**Directory-as-contract.** Each subagent gets a directory with `task.json`
(input), `state.json` (live projection), and `events.jsonl` (audit log). The
spawn command carries the directory path and the MCP endpoint URL.

**Default-deny permissions.** Every tool call passes through a permission
fence. Roles cannot use tools outside their scope. Planning roles can only
write inside the epic directory. The intake phase's Extract step additionally
blocks scouting and writing tools at the mechanism level.

**Driver determinism.** The driver (`koan/driver.py`) reads JSON and exit codes,
applies routing rules, and spawns the next subagent. It never parses markdown
or adapts to LLM behavior. Routing decisions are deterministic.

**HTTP MCP.** Subagents connect to the driver's MCP endpoint at
`/mcp?agent_id={id}`. Tool calls arrive as HTTP requests; the driver looks up
the agent's state by `agent_id` in an in-process registry and handles the call
directly. No separate MCP server processes, no file-based IPC polling.

## Configuration

Model tiers and scout concurrency are configured via the web UI at pipeline
start, then saved to `~/.koan/config.json`:

```json
{
  "modelTiers": {
    "strong": "claude-opus-4-5",
    "standard": "claude-sonnet-4-5",
    "cheap": "claude-haiku-4-5"
  },
  "scoutConcurrency": 4
}
```

Roles map to tiers: intake/decomposer/orchestrator/planner -> strong,
executor -> standard, scout -> cheap.

## Architecture Documentation

- **[docs/architecture.md](./docs/architecture.md)** -- core invariants,
  design principles, pitfalls
- **[docs/subagents.md](./docs/subagents.md)** -- spawn lifecycle, step-first
  workflow, permissions, model tiers
- **[docs/ipc.md](./docs/ipc.md)** -- HTTP MCP inter-process communication,
  blocking tool calls
- **[docs/state.md](./docs/state.md)** -- driver state machine, story lifecycle,
  routing rules
- **[docs/intake-loop.md](./docs/intake-loop.md)** -- confidence-gated intake
  loop, prompt engineering principles
- **[docs/epic-brief.md](./docs/epic-brief.md)** -- brief artifact, brief-writer
  subagent, downstream references
- **[docs/artifact-review.md](./docs/artifact-review.md)** -- artifact review
  protocol, review loop, reusability
- **[docs/token-streaming.md](./docs/token-streaming.md)** -- runner stdout
  parsing, SSE delta path
