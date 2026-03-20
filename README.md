# Koan

Koan is a deterministic planning pipeline for the pi coding agent. It takes a
conversation describing a coding task and produces working code — through a
structured sequence of isolated LLM subagents, each with a narrow, auditable
responsibility.

## How it works

```
Conversation
  → Intake (confidence-gated investigation loop)
  → Decomposer (splits scope into stories)
  → Review gate (user approves story list)
  → Story loop:
      Orchestrator (selects + verifies) → Planner → Executor → repeat
  → Done
```

Each stage is a separate `pi -p` subprocess. Subagents communicate through
files in a per-session directory, not through shared memory or sockets. The
parent driver reads JSON state and exit codes; it never parses LLM output.

## Phases

| Phase | Role | What it does |
|-------|------|-------------|
| **Intake** | `intake` | Reads the conversation, scouts the codebase, asks clarifying questions. Iterates until confident. Writes `context.md`. |
| **Scout** | `scout` | Narrow codebase investigator. Spawned in parallel by intake, decomposer, and planner via `koan_request_scouts`. |
| **Decomposer** | `decomposer` | Reads `context.md`, splits work into story sketches. Each story = one pull request. |
| **Orchestrator** | `orchestrator` | Selects the next story, verifies execution results, routes to retry/done/next. |
| **Planner** | `planner` | Reads a story sketch, writes a step-by-step implementation plan and code context file. |
| **Executor** | `executor` | Follows the plan, modifies the codebase, reports what changed. |

## Web Dashboard

Koan serves a local web dashboard at `http://localhost:{port}` during pipeline
execution. The dashboard provides:

- **Activity feed** — real-time tool calls, scout dispatches, thinking traces
- **Agent monitor** — status, token counts, and recent actions for each
  running subagent
- **User interaction** — question forms (intake clarifications), review gates
  (story approval), model configuration

The dashboard uses Server-Sent Events for real-time updates. State is polled
from each subagent's audit projection every 50ms.

## Key Concepts

**Step-first workflow.** Every subagent's first action is calling
`koan_complete_step`. This forces a tool call before any text output — critical
because `pi -p` processes exit the moment the LLM produces text without a tool
call. Task instructions are delivered as the return value of that first call.

**Directory-as-contract.** Each subagent gets a directory with `task.json`
(input), `state.json` (live projection), and `events.jsonl` (audit log). The
spawn command carries only the directory path. No structured data flows through
CLI flags.

**Default-deny permissions.** Every tool call passes through a permission
fence. Roles cannot use tools outside their scope. Planning roles can only
write inside the epic directory. The intake phase's Extract step additionally
blocks scouting and writing tools at the mechanism level.

**Driver determinism.** The driver (`driver.ts`) reads JSON and exit codes,
applies routing rules, and spawns the next subagent. It never parses markdown
or adapts to LLM behavior. Routing decisions are deterministic.

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

Roles map to tiers: intake/decomposer/orchestrator/planner → strong,
executor → standard, scout → cheap.

## Architecture Documentation

- **[docs/architecture.md](./docs/architecture.md)** — core invariants,
  design principles, pitfalls
- **[docs/subagents.md](./docs/subagents.md)** — spawn lifecycle, step-first
  workflow, permissions, model tiers
- **[docs/ipc.md](./docs/ipc.md)** — file-based IPC between subagent and parent
- **[docs/state.md](./docs/state.md)** — driver state machine, story lifecycle,
  routing rules
- **[docs/intake-loop.md](./docs/intake-loop.md)** — confidence-gated intake
  loop, prompt engineering principles
