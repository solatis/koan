# Koan Architecture Invariants

Full architecture documentation: **[docs/architecture.md](docs/architecture.md)**

## Frontend Design System (read before any frontend work)

The frontend uses a strict token-driven component system. Visual identity
is user-controlled — agents implement it but do not change it without
approval. Violations compound: a misplaced color becomes a wrong token
becomes an inconsistent component becomes a broken design language.

**When touching any file under `frontend/`**, read
**[frontend/AGENTS.md](frontend/AGENTS.md)** first. It defines protected
files, the component hierarchy (atoms → molecules → organisms), and CSS
conventions.

**When building or modifying a UI component**, also read
**[frontend/src/components/AGENTS.md](frontend/src/components/AGENTS.md)**.
It contains the development rules, the tier decision tree, and the
verification checklist.

---

Spoke documents:

- [docs/subagents.md](docs/subagents.md) -- spawn lifecycle, task manifest, step-first workflow, permissions
- [docs/ipc.md](docs/ipc.md) -- HTTP MCP tool calls, blocking interactions, scout spawning, koan_yield blocking
- [docs/state.md](docs/state.md) -- driver/LLM boundary, run state, orchestrator state
- [docs/intake-loop.md](docs/intake-loop.md) -- three-step intake design, prompt engineering
- [docs/projections.md](docs/projections.md) -- versioned event log, fold function, projection shape, SSE protocol, version-negotiated catch-up
- [docs/token-streaming.md](docs/token-streaming.md) -- runner stdout parsing, SSE delta path

**Workflow types:** `plan` (intake → plan-spec → plan-review → execute) · `milestones` (stub: intake only)

---

The six core invariants (see architecture.md for full detail + pitfalls):

## 1. File Boundary

LLMs write **markdown files only**. The driver maintains **JSON state files**
internally -- no LLM ever reads or writes a `.json` file. Tool code bridges
both worlds.

## 2. Step-First Workflow Pattern (critical)

The orchestrator is a single long-lived CLI process (`claude`, `codex`, or
`gemini`) that runs the entire workflow. It connects to the driver's HTTP MCP
endpoint at `http://localhost:{port}/mcp?agent_id={id}` and receives tools via
MCP. The driver handles all tool logic in-process.

**The first thing the orchestrator does is call `koan_complete_step`.** The
spawn prompt contains _only_ this directive. The tool returns step 1
instructions. This establishes the calling pattern before the LLM sees complex
instructions.

```
Boot prompt:  "You are a koan orchestrator agent. Call koan_complete_step to receive your instructions."
     | LLM calls koan_complete_step (step 0 -> 1 transition)
Tool returns:  Step 1 instructions (phase role context + task details)
     | LLM does work...
     | LLM calls koan_complete_step
Tool returns:  Step 2 instructions (or phase-boundary response)
```

When a phase ends, `koan_complete_step` returns a **non-blocking** response
telling the orchestrator to summarize and call `koan_yield`. `koan_yield` is
the generic conversation primitive — it blocks until the user sends a message,
then returns that message as the tool result. The orchestrator calls `koan_yield`
repeatedly for multi-turn conversation, then calls `koan_set_phase` to commit
the transition. Passing `koan_set_phase("done")` ends the workflow (tombstone).
The step counter resets to 0 on each `koan_set_phase` call, then advances to 1
on the next `koan_complete_step`. Phase-specific role context (`SYSTEM_PROMPT`)
is injected into that step-1 response.

Step progression is normally linear within a phase, but phase modules may
override `get_next_step()` to implement non-linear flows. See
[docs/intake-loop.md](docs/intake-loop.md).

Executor subagents are spawned by the orchestrator via `koan_request_executor`.
Scout subagents are spawned via `koan_request_scouts`.

## 3. Driver Determinism (partially relaxed)

The driver (`koan/driver.py`) spawns the orchestrator and awaits its exit.
Phase routing is driven by the orchestrator via `koan_set_phase` rather than
the driver's routing loop.

The driver still:
- Validates every phase transition (`is_valid_transition()` in the tool handler)
- Updates `run-state.json` atomically
- Emits projection events
- Enforces the permission fence

The driver does **not** decide which phase runs next. Invalid phase strings
raise `ToolError`; valid transitions are committed. All routing decisions flow
through typed tool parameters, not free text.

`is_valid_transition(workflow, from_phase, to_phase)` checks that `to_phase` is
in the active workflow's `available_phases` and is not equal to `from_phase`.
Any phase in the workflow is reachable from any other — there is no DAG of
required successors.

## 4. Default-Deny Permissions

Every tool call passes through a role-based permission fence. Unknown roles
and tools are blocked. The orchestrator role uses **phase-aware permissions**:
available tools vary by `current_phase`. Planning-phase write access is
path-scoped to the run directory.

The fence also supports step-level gating: `write` and `edit` are blocked
during brief-generation step 1 (the read step).

**Orchestrator tool availability by phase:**

| Tool | Available phases |
|------|-----------------|
| `koan_complete_step` | All phases |
| `koan_set_phase` | All phases (blocked mid-story during execution); accepts `"done"` as tombstone |
| `koan_yield` | All phases |
| `koan_ask_question` | All phases |
| `koan_request_scouts` | `intake`, `core-flows`, `tech-plan`, `ticket-breakdown`, `cross-artifact-validation`, `plan-spec`, `plan-review` |
| `koan_request_executor` | `execution`, `execute` |
| `koan_select_story`, `koan_complete_story`, `koan_retry_story`, `koan_skip_story` | `execution` only |
| `write`, `edit` (run_dir scoped) | All phases except `brief-generation` step 1 |
| `bash` | `execution`, `implementation-validation` |

## 5. Need-to-Know Prompts

Boot prompt is one sentence. System prompt is minimal (orchestrator identity
only). Phase-specific role context arrives via step 1 guidance after
`koan_set_phase` is called -- the orchestrator doesn't know its next role until
`koan_complete_step` tells it.

Each workflow provides a `phase_guidance` injection for the phases it defines.
This injection appears at the top of step 1 guidance and sets workflow-specific
posture (investigation depth, question aggressiveness, what to hand off to the
executor). See [docs/architecture.md](docs/architecture.md) for the injection contract.

## 6. Directory-as-Contract

The orchestrator has one subagent directory for the entire run. Executor and
scout subagents each get their own directory per the standard contract:

| File           | Writer                    | Reader                         | Purpose            |
| -------------- | ------------------------- | ------------------------------ | ------------------ |
| `task.json`    | Parent (before spawn)     | Parent (at agent registration) | What to do         |
| `state.json`   | Parent (audit projection) | Available for debugging        | What has been done |
| `events.jsonl` | Parent (audit log)        | Available for replay           | Full event history |

The `mcp_url` field in `task.json` tells the child where to connect for tool
calls. No structured configuration flows through CLI flags. The spawn command
carries the directory path and the MCP config pointing at the driver's HTTP
endpoint.

The `task.json` for every subagent includes `run_dir` — the path to the current
workflow run directory (`~/.koan/runs/<id>/`).
