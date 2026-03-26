# State & Driver

How the driver manages epic and story state, routes between phases, and
enforces the file boundary invariant.

> Parent doc: [architecture.md](./architecture.md)

---

## The File Boundary in Practice

The driver writes JSON; LLMs write markdown. Tool code bridges both.

| Actor         | Reads                           | Writes                              |
| ------------- | ------------------------------- | ----------------------------------- |
| **Driver**    | `.json` state files, exit codes | `.json` state files                 |
| **LLM**       | `.md` files, codebase files     | `.md` files (output)                |
| **Tool code** | `.json` state (to validate)     | `.json` state + `.md` status (both) |

### Why the epic state module must not write markdown

The epic state module (`koan/epic_state.py`) reads and writes JSON only.
`status.md` writes belong exclusively in orchestrator tool handlers, which
bridge the two worlds by writing JSON state (for the driver) and templated
markdown (for LLMs) in the same operation.

### Filesystem-driven story discovery

Story IDs are discovered by scanning `stories/*/story.md`, not by reading a
driver-maintained JSON list. The decomposer LLM creates `story.md` files using
the `write` tool -- it has no reason to know the JSON state format. The driver
discovers what the LLM created by scanning, then populates the JSON story list
itself.

---

## Epic State

`epic-state.json` in the epic directory root. Tracks the current pipeline
phase and the list of story IDs.

```python
# koan/epic_state.py
{
    "phase": "intake",  # intake -> brief-generation -> core-flows -> tech-plan
                        # -> ticket-breakdown -> cross-artifact-validation
                        # -> execution -> implementation-validation -> completed
    "stories": []       # populated by driver after filesystem scan
}
```

### Epic phases

| Phase                       | What happens                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| `intake`                    | Intake subagent reads conversation, scouts codebase, asks user questions                    |
| `brief-generation`          | Brief-writer subagent distills landscape.md into brief.md; user reviews via artifact review |
| `core-flows`                | Define user journeys with sequence diagrams                                                 |
| `tech-plan`                 | Specify technical architecture                                                              |
| `ticket-breakdown`          | Generate story-sized implementation tickets                                                 |
| `cross-artifact-validation` | Validate cross-boundary consistency                                                         |
| `execution`                 | Implement tickets through supervised batch process                                          |
| `implementation-validation` | Post-execution alignment review                                                             |
| `completed`                 | All phases done                                                                             |

Additional epic directory files:

| File                     | Purpose                                            |
| ------------------------ | -------------------------------------------------- |
| `workflow-decision.json` | Records workflow orchestrator decisions            |
| `workflow-status.md`     | Human-readable workflow status for LLM consumption |

**`scouting` is intentionally absent.** Scouts run inside the
`koan_request_scouts` tool handler during intake/decomposer/planner phases,
not as a top-level phase.

---

## Story State

One `state.json` per story in `stories/{story_id}/`.

```python
{
    "story_id": "auth-middleware",
    "status": "pending",
    "retry_count": 0,
    "max_retries": 2,
    "failure_summary": None,   # set by koan_retry_story
    "skip_reason": None,       # set by koan_skip_story or driver
    "updated_at": "2026-03-27T..."
}
```

### Story status lifecycle

```
pending --> selected --> planning --> executing --> verifying --> done
   |            ^                                       |
   |            +------------- retry <------------------+
   |                                                    |
   +---> skipped <--------------------------------------+
```

| Status      | Set by                                     | Meaning                                   |
| ----------- | ------------------------------------------ | ----------------------------------------- |
| `pending`   | Driver (initial)                           | Story exists, not yet started             |
| `selected`  | Orchestrator (`koan_select_story`)         | Chosen for execution                      |
| `planning`  | Driver                                     | Planner subagent is running               |
| `executing` | Driver                                     | Executor subagent is running              |
| `verifying` | Driver                                     | Post-execution orchestrator is evaluating |
| `done`      | Orchestrator (`koan_complete_story`)       | Successfully completed                    |
| `retry`     | Orchestrator (`koan_retry_story`)          | Failed, queued for re-execution           |
| `skipped`   | Orchestrator (`koan_skip_story`) or Driver | Permanently skipped                       |

### No `escalated` status

Escalation is handled via `koan_ask_question` -- the orchestrator asks the user
a question through MCP, gets an answer, then decides `retry` or `skip`.

### Retry budget

Each story starts with `max_retries: 2`. When the driver sees `status: "retry"`,
it increments `retry_count` and re-executes. When `retry_count >= max_retries`,
the driver sets the story to `skipped`.

---

## Driver Routing

The driver's story loop is a deterministic state machine:

```python
# koan/driver.py
while True:
    stories = load_all_story_states(epic_dir)
    routing = route_from_state(stories)

    if routing.action == "retry":    # re-execute story
    elif routing.action == "execute": # plan + execute story
    elif routing.action == "complete": # all stories terminal -> exit loop
    elif routing.action == "error":   # no actionable state -> fail
```

**Priority:** `retry` is checked before `selected`. A story queued for retry
takes precedence over a newly selected story.

**Terminal states:** exactly `done` and `skipped`. The epic is complete when
every story is in a terminal state.

**Error state:** If no story is `retry` or `selected` and not all are terminal,
the driver reports: "orchestrator may have exited without a routing decision."

### Story execution pipeline

For each story selected for execution:

```
Driver sets status -> planning
  -> spawn planner subagent
  -> if planner fails: skip executor, go to post-execution orchestrator
Driver sets status -> executing
  -> spawn executor subagent
Driver sets status -> verifying
  -> spawn orchestrator (post-execution)
  -> orchestrator decides: koan_complete_story / koan_retry_story / koan_skip_story
```

### Planner failure fallthrough

When the planner exits with non-zero exit code, the driver skips the executor
and proceeds directly to the post-execution orchestrator. This gives the
orchestrator a chance to make a routing decision.

### Model config gate

When a web server is available, the pipeline blocks at startup until the user
confirms model tier selection. This happens before any subagent spawns.

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

- `epic-state.json` (driver)
- `stories/{id}/state.json` (driver + orchestrator tools)
- `stories/{id}/status.md` (orchestrator tools)
- `subagents/{label}/task.json` (driver, before spawn)
- `subagents/{label}/state.json` (audit projection)

---

## Epic Directory Structure

```
{epic_dir}/
  epic-state.json           # Epic phase + story list
  workflow-decision.json    # Workflow orchestrator decisions
  workflow-status.md        # Human-readable workflow status
  landscape.md              # Written by intake
  brief.md                  # Written by brief-writer
  stories/
    {story_id}/
      story.md              # Written by decomposer
      state.json            # Story lifecycle state
      status.md             # Templated status for LLM consumption
      plan/
        plan.md             # Written by planner
  subagents/
    intake/
      task.json             # Task manifest
      state.json            # Audit projection
      events.jsonl          # Audit log
    decomposer/
      ...
    scout-{id}-{timestamp}/
      task.json
      findings.md           # Scout output
      ...
    planner-{story_id}/
      ...
    executor-{story_id}/
      ...
    orchestrator-pre/
      ...
    orchestrator-post-{story_id}/
      ...
```

---

## Audit Projection (`state.json`)

Each subagent's `state.json` is an eagerly-materialized summary written
atomically after every audit event. It is available on disk for debugging and
post-mortem analysis. Live SSE events are pushed directly from in-process state
transitions.

Key projection fields common to all roles:

| Field             | Type   | Meaning                                                 |
| ----------------- | ------ | ------------------------------------------------------- |
| `phase`           | string | Overall phase name (e.g., "intake", "brief-generation") |
| `step`            | number | Current step index within the phase                     |
| `step_name`       | string | Human-readable step label (e.g., "Scout (round 2)")     |
| `tokens_sent`     | number | Cumulative tokens in                                    |
| `tokens_received` | number | Cumulative tokens out                                   |

Intake-specific fields (zero/null for all other roles):

| Field               | Type                                                    | Meaning                          |
| ------------------- | ------------------------------------------------------- | -------------------------------- |
| `intake_confidence` | `"exploring"\|"low"\|"medium"\|"high"\|"certain"\|null` | Last confidence level            |
| `intake_iteration`  | number                                                  | Current loop iteration (1-based) |
