# State & Driver

How the driver manages run state, routes between phases, and enforces the file
boundary invariant.

> Parent doc: [architecture.md](./architecture.md)

---

## The File Boundary in Practice

The driver writes JSON; LLMs write markdown. Tool code bridges both.

| Actor         | Reads                           | Writes                              |
| ------------- | ------------------------------- | ----------------------------------- |
| **Driver**    | `.json` state files, exit codes | `.json` state files                 |
| **LLM**       | `.md` files, codebase files     | `.md` files (output)                |
| **Tool code** | `.json` state (to validate)     | `.json` state + `.md` status (both) |

### Why the run state module must not write markdown

The run state module (`koan/run_state.py`) reads and writes JSON only.
`status.md` writes belong exclusively in orchestrator tool handlers, which
bridge the two worlds by writing JSON state (for the driver) and templated
markdown (for LLMs) in the same operation.

---

## Run State

`run-state.json` in the run directory root. Tracks the current workflow phase,
the active workflow type, and the list of story IDs.

```python
# koan/run_state.py
{
    "phase": "intake",        # current phase name; valid values depend on the active workflow
    "workflow": "plan"        # workflow type selected at run start ("plan" | "milestones")
}
```

### Plan workflow phases

| Phase      | What happens                                                                                                                                                                         |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `intake`   | Orchestrator reads conversation, scouts codebase, asks clarifying questions. Writes `brief.md`.                                                                                      |
| `plan`     | Orchestrator reads codebase and `brief.md`, writes `plan.md` (triggers mechanical PLAN_REVIEWER).                                                                                    |
| `execute`  | Orchestrator calls `koan_request_executor(plan_file?, instructions?)` to spawn the executor and receive the deviation report; runs independent verification; records outcome inline. |
| `curation` | Postmortem -- writes memory entries via `koan_memorize`/`koan_forget`.                                                                                                               |

Phases advance via `koan_set_phase`; the active workflow switches via
`koan_set_workflow` (which also lands at the new workflow's initial phase). Any phase in the active workflow's
`available_phases` is a valid transition target from any other phase (except
self-transitions). The suggested transitions in `workflow.suggested_transitions`
guide the orchestrator's default boundary response but do not restrict the user.

**`scouting` is intentionally absent.** Scouts run inside the
`koan_request_scouts` tool handler during intake/planning phases,
not as a top-level phase.

---

## Driver and Orchestrator

The driver spawns the orchestrator once at run start and awaits its exit.
The orchestrator drives the entire workflow, including phase transitions and
story execution.

### Model config gate

When a web server is available, the pipeline blocks at startup until the user
confirms model tier selection and workflow type. This happens before the orchestrator spawns.

---

## Atomic Writes

All state writes use atomic tmp-file + rename via `os.rename()`:

```python
tmp = f"{file_path}.tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.rename(tmp, file_path)
```

This applies to:

- `run-state.json` (driver)
- `subagents/{label}/task.json` (driver, before spawn)
- `subagents/{label}/state.json` (audit projection)

---

## Run Directory Structure

```
~/.koan/runs/{run_id}/
  run-state.json            # Workflow phase + workflow type
  brief.md                  # Written by orchestrator (intake phase)
  plan.md                   # Written by orchestrator (plan phase)
  subagents/
    orchestrator/
      task.json             # Task manifest (written once at run start)
      state.json            # Audit projection
      events.jsonl          # Audit log (covers entire run, all phases)
    scout-{id}-{timestamp}/
      task.json
      findings.md           # Scout output
      ...
    executor-{run_id}/
      task.json
      state.json
      events.jsonl
```

---

## Audit Projection (`state.json`)

Each subagent's `state.json` is an eagerly-materialized summary written
atomically after every audit event. It is available on disk for debugging and
post-mortem analysis. Live SSE events are pushed directly from in-process state
transitions.

Key projection fields common to all roles:

| Field             | Type   | Meaning                                             |
| ----------------- | ------ | --------------------------------------------------- |
| `phase`           | string | Overall phase name (e.g., "intake", "plan")         |
| `step`            | number | Current step index within the phase                 |
| `step_name`       | string | Human-readable step label (e.g., "Scout (round 2)") |
| `tokens_sent`     | number | Cumulative tokens in                                |
| `tokens_received` | number | Cumulative tokens out                               |

Orchestrator state tracked in `AppState` (in-memory, not persisted):

| Field                 | Type                     | Purpose                                                                                     |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------- |
| `workflow`            | `Workflow \| None`       | Active workflow; set at run start, drives transition validation and phase guidance          |
| `user_message_buffer` | `list[ChatMessage]`      | Buffered user chat messages, drained when the loop resumes from a hand-back                 |
| `yield_future`        | `asyncio.Future \| None` | Non-None while the loop is parked at a phase-boundary hand-back, waiting for a user message |
| `workflow_done`       | `bool`                   | Set to `True` by `koan_set_phase("done")`; causes the loop to terminate                     |

Per-agent state in `AgentState`:

| Field                  | Type          | Purpose                                                                                                                                        |
| ---------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `first_turn_completed` | `bool`        | Set by `run_agent_loop` when the first turn reaches the End node; the bootstrap success signal replacing the former first-tool-call handshake  |
| `provider`             | `str \| None` | Provider name from `model_spec`; used by the fold to derive cost                                                                               |
| `context_window`       | `int`         | Context window size from `model_spec`; used by the fold to derive context-window percent                                                       |
| `injected_artifacts`   | `set`         | Artifact basenames already injected as `<handoff_artifact>` messages; per-agent dedup key that persists for the agent's whole life             |
| `pending_artifacts`    | `list`        | Artifact basenames queued at phase entry by `_step_phase_handshake_core`; drained by `preseed_pending_artifacts` before the next model request |
| `message_history`      | `list`        | Driver-owned `ModelMessage` list accumulated across turns; passed as `message_history` to each `agent.iter()` call                             |

`injected_artifacts` / `pending_artifacts` mirror the earlier
`injected_context_files` / `pending_context_files` pair introduced for
context-file injection. The drain-read-wrap-append-mark cycle is implemented
by `preseed_pending_artifacts` in `koan/tools/handoff_artifacts.py`. A
`FileNotFoundError` at drain time silently skips the artifact (producer phase
may have been yield-skipped); other `OSError` faults inject a visible error
placeholder with `error="true"` so gaps are never silently hidden.

`InteractionState` carries `next_suggestions: list[dict] \| None`, the
orchestrator-authored hand-back suggestions recorded by `koan_suggest_next`.
The loop consumes and clears them at the hand-back, falling back to the
deterministic `build_phase_suggestions` when none are present.

`ChatMessage` carries `content: str` and `timestamp_ms: int`. Messages are
appended by `POST /api/chat` and removed atomically by `drain_user_messages()`.
