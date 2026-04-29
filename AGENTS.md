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
- [docs/initiative.md](docs/initiative.md) -- initiative workflow contract, band hierarchy, gating
- [docs/ipc.md](docs/ipc.md) -- HTTP MCP tool calls, blocking interactions, scout spawning, koan_yield blocking
- [docs/state.md](docs/state.md) -- driver/LLM boundary, run state, orchestrator state
- [docs/intake-loop.md](docs/intake-loop.md) -- two-step intake design, prompt engineering
- [docs/phase-trust.md](docs/phase-trust.md) -- phase trust model, verification boundaries, adversarial review
- [docs/projections.md](docs/projections.md) -- versioned event log, fold function, projection shape, SSE protocol, version-negotiated catch-up
- [docs/token-streaming.md](docs/token-streaming.md) -- runner stdout parsing, SSE delta path
- [docs/milestones.md](docs/milestones.md) -- milestone soundness criteria, sizing heuristics, grounding requirements
- [docs/workflow-phases.md](docs/workflow-phases.md) -- phase taxonomy across all workflows, producer-validator pairing

**Workflow types:** `plan` (intake -> plan-spec -> plan-review -> execute -> exec-review -> curation) . `milestones` (intake -> milestone-spec -> [milestone-review] -> plan-spec -> [plan-review] -> execute -> exec-review -> milestone-spec loop -> curation) . `initiative` (intake -> core-flows -> tech-plan-spec -> tech-plan-review -> milestone-spec -> [milestone-review] -> plan-spec -> [plan-review] -> execute -> exec-review -> milestone-spec loop -> curation) . `discovery` (frame; single-phase exploration)

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

Two enforcement layers restrict what tools each agent can use:

1. **CLI tool whitelist** (`CLAUDE_TOOL_WHITELISTS` in `subagent.py`) --
   controls which built-in tools exist in the model's context. Unlisted tools
   are not presented to the model; it cannot call them. Agents should not have
   access to tools they are never intended to need.
2. **MCP permission fence** (`check_permission()` in `permissions.py`) --
   gates koan MCP tool calls per role and phase. Unknown roles and tools are
   blocked.

The fence also supports step-level gating: `write` and `edit` are blocked
during brief-generation step 1 (the read step).

**CLI tool whitelists (per agent type):**

| Role         | Built-in tools                                                                                                               |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| orchestrator | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch`, `WebSearch`                                                     |
| executor     | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`, `TaskStop`, `TaskOutput` |
| scout        | `Read`, `Bash`, `Glob`, `Grep`                                                                                               |

**MCP permission fence -- orchestrator tool availability by phase:**

| Tool                                                                              | Available phases                                                                                                                                       |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `koan_complete_step`                                                              | All phases                                                                                                                                             |
| `koan_set_phase`                                                                  | All phases (blocked mid-story during execution); accepts `"done"` as tombstone                                                                         |
| `koan_set_workflow`                                                               | All phases (matches `koan_set_phase`); accepts any registered workflow name; always lands at the new workflow's `initial_phase`                        |
| `koan_yield`                                                                      | All phases                                                                                                                                             |
| `koan_ask_question`                                                               | All phases                                                                                                                                             |
| `koan_request_scouts`                                                             | `intake`, `core-flows`, `tech-plan-spec`, `tech-plan-review`, `ticket-breakdown`, `cross-artifact-validation`, `plan-spec`, `plan-review`, `milestone-spec`, `milestone-review` |
| `koan_request_executor`                                                           | `execution`, `execute`                                                                                                                                 |
| `koan_select_story`, `koan_complete_story`, `koan_retry_story`, `koan_skip_story` | `execution` only                                                                                                                                       |
| `bash`                                                                            | `execution`, `implementation-validation`, `exec-review`                                                                                                |
| `koan_memorize`                                                                   | All phases                                                                                                                                             |
| `koan_forget`                                                                     | All phases                                                                                                                                             |
| `koan_memory_status`                                                              | All phases                                                                                                                                             |
| `koan_search`                                                                     | All phases                                                                                                                                             |
| `koan_reflect`                                                                    | All phases (orchestrator only)                                                                                                                         |
| `koan_artifact_write`                                                             | All phases (orchestrator only)                                                                                                                         |
| `koan_artifact_list`                                                              | All phases (all roles via universal read-tool path)                                                                                                    |
| `koan_artifact_view`                                                              | All phases (all roles via universal read-tool path)                                                                                                    |

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

| File           | Writer                                                                   | Reader                         | Purpose            |
| -------------- | ------------------------------------------------------------------------ | ------------------------------ | ------------------ |
| `task.json`    | Parent (before spawn; orchestrator also appended by `koan_set_workflow`) | Parent (at agent registration) | What to do         |
| `state.json`   | Parent (audit projection)                                                | Available for debugging        | What has been done |
| `events.jsonl` | Parent (audit log)                                                       | Available for replay           | Full event history |

The `mcp_url` field in `task.json` tells the child where to connect for tool
calls. No structured configuration flows through CLI flags. The spawn command
carries the directory path and the MCP config pointing at the driver's HTTP
endpoint.

The `task.json` for every subagent includes `run_dir` — the path to the current
workflow run directory (`~/.koan/runs/<id>/`).

The orchestrator `task.json` carries `workflow_history` (an append-only list of
`{name, phase, started_at}` entries) rather than a single `workflow` string. The
most-recent entry is the active workflow. The list grows by one entry on each
`koan_set_workflow` call; executor and scout `task.json` files do not carry this
field.
