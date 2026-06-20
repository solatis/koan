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

- [docs/agent-protocol.md](docs/agent-protocol.md) -- Agent Protocol, AgentOptions, PydanticAIAgent, steering integration, provider adapter
- [docs/subagents.md](docs/subagents.md) -- spawn lifecycle, task manifest, step-first workflow, permissions
- [docs/initiative.md](docs/initiative.md) -- initiative workflow contract, band hierarchy, gating
- [docs/ipc.md](docs/ipc.md) -- in-process tool calls, blocking interactions, scout spawning, terminal-text hand-back
- [docs/state.md](docs/state.md) -- driver/LLM boundary, run state, orchestrator state
- [docs/intake-loop.md](docs/intake-loop.md) -- two-step intake design, prompt engineering
- [docs/phase-trust.md](docs/phase-trust.md) -- phase trust model, verification boundaries, adversarial review
- [docs/projections.md](docs/projections.md) -- versioned event log, fold function, projection shape, SSE protocol, version-negotiated catch-up
- [docs/token-streaming.md](docs/token-streaming.md) -- in-process StreamEvent delta path, SSE bridge
- [docs/tools.md](docs/tools.md) -- tool-layer strategy: trusted/untrusted taxonomy, read/grep output format, hash-anchored edit protocol
- [docs/tool-output-limits.md](docs/tool-output-limits.md) -- tool-result size strategy, untrusted (reject) vs trusted (bound-by-construction) classes
- [docs/milestones.md](docs/milestones.md) -- milestone soundness criteria, sizing heuristics, grounding requirements
- [docs/workflow-phases.md](docs/workflow-phases.md) -- phase taxonomy across all workflows, mechanical reviewer and inline execute review
- [docs/artifacts.md](docs/artifacts.md) -- artifact registry, filename grammar, reviewer lifecycle, sidecar

**Workflow types:** `plan` (intake -> plan -> execute -> curation) . `milestones` (intake -> milestone -> plan -> execute -> milestone loop -> curation) . `initiative` (intake -> core-flows -> tech-plan -> milestone -> plan -> execute -> milestone loop -> curation) . `discovery` (frame; single-phase exploration)

---

The six core invariants (see architecture.md for full detail + pitfalls):

**Provider credential model:** Provider availability is `ProviderStatus`
(env-key presence). There is no binary probe. The all-providers model registry
(`ModelRegistryEntry`) is built from the genai-prices bundled snapshot joined
with a koan-owned capability table in `koan/agents/model_catalog.py`. Cost
derivation uses `price_for_usage` against the bundled snapshot only.

## 1. File Boundary

LLMs write **markdown files only**. The driver maintains **JSON state files**
internally -- no LLM ever reads or writes a `.json` file. Tool code bridges
both worlds.

## 2. Step-First Workflow Pattern (critical)

The orchestrator runs as an asyncio task inside the single backend process.
Tools are in-process `FunctionToolset`s composed per (role, phase) via
`compose_toolset` in `koan/tools/tool_policy.py`. There is no boot prompt and
no step-advance tool call.

**Step 1 guidance is injected as the first turn prompt.** The loop
(`run_agent_loop` in `koan/agents/loop.py`) bootstraps by calling
`_step_phase_handshake_core` to obtain step 1 guidance and injects it as
the initial user turn. A **turn-outcome resolver** (`resolve_turn_outcome`)
runs at each end-of-turn (terminal-text turn with no outstanding tool calls):

```
Loop injects step 1 guidance as first turn prompt
     | Agent does work, calls tools as needed
     | Agent ends turn in terminal text (no outstanding tool call)
Resolver fires:
  - completion gate fails  -> re-inject the same step
  - more steps remain      -> inject next step guidance
  - steps exhausted, primary agent -> hand back to user
  - steps exhausted, non-primary   -> terminate
```

At the phase boundary, the primary agent calls `koan_suggest_next` to record
the suggested next steps, then ends its turn in terminal text. The loop surfaces
the text and suggestions and parks awaiting the user. The user's reply resumes
the loop. The agent then calls `koan_set_phase` to commit the transition.
Passing `koan_set_phase("done")` ends the workflow (tombstone).

Phase-specific role context (`SYSTEM_PROMPT`) is prepended to the step 1
guidance at the top of the first turn. Step progression is normally linear
within a phase, but phase modules may override `get_next_step()` to implement
non-linear flows. See [docs/intake-loop.md](docs/intake-loop.md).

Reviewer subagents are spawned mechanically by koan when `koan_artifact_write`
is called for a reviewed artifact family (plan, milestones, tech-plan). The
reviewer runs in a fresh context, returns freeform findings, and koan persists
them to the `.review.md` sidecar. The executor is spawned via
`koan_set_phase("execute", plan_file=...)` -- this freezes the named plan and
returns the deviation report. Scout subagents are spawned via `koan_request_scouts`.

## 3. Driver Determinism (partially relaxed)

The driver (`koan/driver.py`) spawns the orchestrator and awaits its exit.
Phase routing is driven by the orchestrator via `koan_set_phase` rather than
the driver's routing loop.

The driver still:

- Validates every phase transition (`is_valid_transition()` in the tool handler)
- Updates `run-state.json` atomically
- Emits projection events

The driver does **not** decide which phase runs next. Invalid phase strings
raise a domain exception; valid transitions are committed. All routing decisions
flow through typed tool parameters, not free text.

`is_valid_transition(workflow, from_phase, to_phase)` checks that `to_phase` is
in the active workflow's `available_phases` and is not equal to `from_phase`.
Any phase in the workflow is reachable from any other — there is no DAG of
required successors.

## 4. Default-Deny Permissions

Capability restriction is **construction-time**, not call-time.
`compose_toolset(policy, role, phase)` in `koan/tools/tool_policy.py` builds
the allowed tool vocabulary once per (role, phase) before the agent's loop
starts. Disallowed tools never enter the model's context; the model cannot
call what it cannot see. The allowlist tables (`ROLE_PERMISSIONS` and the
universal read/memory sets) live in `tool_policy.py` and are the single source
of truth.

**Per-role built-in tool vocabulary** (composed via `compose_toolset`):

| Role         | Built-in tools                                                           |
| ------------ | ------------------------------------------------------------------------ |
| orchestrator | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch`, `WebSearch` |
| executor     | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`                          |
| reviewer     | `Read`, `Bash`, `Glob`, `Grep` (read-only; no write/edit/scouts)         |
| scout        | `Read`, `Bash`, `Glob`, `Grep`                                           |

**Orchestrator koan tool vocabulary** (composed per phase from `ROLE_PERMISSIONS`):

| Tool                                                                              | Available phases                                                                                                         |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `koan_suggest_next`                                                               | All phases (orchestrator only; records hand-back suggestions before the terminal-text turn)                              |
| `koan_set_phase`                                                                  | All phases; accepts `"done"` as tombstone; `koan_set_phase("execute", plan_file=X)` freezes X and spawns the executor   |
| `koan_set_workflow`                                                               | All phases; accepts any registered workflow name; always lands at the new workflow's `initial_phase`                     |
| `koan_ask_question`                                                               | All phases                                                                                                               |
| `koan_request_scouts`                                                             | `intake`, `core-flows`, `tech-plan`, `plan`, `milestone`, `curation`, `frame`                                           |
| `bash`                                                                            | `execute`, `frame`                                                                                                       |
| `koan_memorize`                                                                   | All phases                                                                                                               |
| `koan_forget`                                                                     | All phases                                                                                                               |
| `koan_memory_status`                                                              | All phases                                                                                                               |
| `koan_search`                                                                     | All phases                                                                                                               |
| `koan_reflect`                                                                    | All phases (orchestrator only)                                                                                           |
| `koan_artifact_write`                                                             | All phases (orchestrator only); triggers the mechanical reviewer sub-agent when the artifact family has a reviewer       |
| `koan_artifact_edit`                                                              | All phases (orchestrator only); freeze-exempt for `.review.md` sidecars                                                 |
| `koan_artifact_list`                                                              | All phases (all roles via universal read-tool path)                                                                      |
| `koan_artifact_read`                                                              | All phases (all roles via universal read-tool path); run-dir-scoped wrapper over `read`                                  |

## 5. Need-to-Know Prompts

There is no boot prompt. The system prompt is minimal (orchestrator identity
only). Phase-specific role context (`SYSTEM_PROMPT`) is prepended to step 1
guidance and injected as the first turn prompt by `run_agent_loop`. The agent
does not receive its role context until the loop starts the first turn.

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

The `task.json` for every subagent includes `run_dir` -- the path to the current
workflow run directory (`~/.koan/runs/<id>/`).

The orchestrator `task.json` carries `workflow_history` (an append-only list of
`{name, phase, started_at}` entries) rather than a single `workflow` string. The
most-recent entry is the active workflow. The list grows by one entry on each
`koan_set_workflow` call; executor and scout `task.json` files do not carry this
field.
