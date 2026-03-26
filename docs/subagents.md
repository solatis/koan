# Subagents

How koan spawns, manages, and terminates LLM subagent processes.

> Parent doc: [architecture.md](./architecture.md)

---

## Task Manifest

Every subagent starts as a CLI process (`claude`, `codex`, or `gemini`) with
MCP config pointing at the driver's HTTP endpoint. The driver reads `task.json`
from the subagent directory to set up the agent's state in the in-process
registry.

### `task.json` schema

The manifest is a discriminated union on the `role` field. Common fields
(`role`, `epic_dir`, `mcp_url`) appear on every variant; role-specific fields
are nested naturally rather than flattened into a shared namespace.

```json
{
  "role": "intake",
  "epic_dir": "/path/to/epic",
  "mcp_url": "http://localhost:8420/mcp?agent_id=intake-abc123"
}
```

Role-specific fields:

| Role           | Additional fields                      |
| -------------- | -------------------------------------- |
| `intake`       | --                                     |
| `scout`        | `output_file`, `investigator_role`     |
| `decomposer`   | --                                     |
| `orchestrator` | `step_sequence`, `story_id` (optional) |
| `planner`      | `story_id`                             |
| `executor`     | `story_id`, `retry_context` (optional) |

### Lifecycle

`task.json` is **write-once, read-once**:

1. Driver creates the subagent directory
2. Driver writes `task.json` (atomic: tmp + rename)
3. Driver assigns `agent_id`, registers agent in in-process registry
4. Driver writes MCP config and spawns the CLI process
5. Child connects to `mcp_url`, calls `koan_complete_step`
6. `task.json` is never modified after spawn

This makes every subagent directory **self-describing** and **inspectable**
after the fact. `cat task.json` shows exactly what the subagent was asked
to do.

### Why not CLI flags

The previous design passed task configuration as 9 CLI flags. Problems:

| Problem                      | Example                                                                    |
| ---------------------------- | -------------------------------------------------------------------------- |
| **Flat namespace collision** | `--koan-role` vs `--koan-scout-role` -- two unrelated concepts             |
| **Unstructured**             | Role-specific fields mixed with common fields                              |
| **Size limits**              | `--koan-retry-context` carries multi-paragraph summaries                   |
| **Uninspectable**            | After a crash, reconstructing what was asked requires parsing process args |

---

## Spawn Flow

### Parent side

```
driver: mkdir subagent_dir
driver: write task.json to subagent_dir (atomic)
driver: assign agent_id, register in agent registry
          -> init step engine, permissions, event log from task.json
driver: write MCP config (runner-specific):
          claude: mcp-config.json
          codex: -c runtime override
          gemini: .gemini/settings.json in cwd
driver: spawn_subagent(task, subagent_dir, runner)
          -> runner.build_command(boot_prompt, mcp_url, model, cwd)
          -> subprocess.Popen(cmd, cwd=cwd, stdout=PIPE, stderr=PIPE)
          -> parse stdout line-by-line for streaming events
          -> wait for process exit
driver: deregister agent_id
driver: check exit code, route to next phase
```

### Child side

```
CLI process starts (claude/codex/gemini)
  -> connects to MCP endpoint at mcp_url
  -> discovers available tools via MCP

LLM receives boot prompt:
  "You are a koan {role} agent. Call koan_complete_step to receive your instructions."
  -> LLM calls koan_complete_step via MCP
  -> MCP endpoint looks up agent_id, advances step 0 -> 1
  -> returns step 1 guidance as tool result
```

### Boot prompt

```
"You are a koan {role} agent. Call koan_complete_step to receive your instructions."
```

One sentence. No task content. The role name is included for primacy -- it
anchors the LLM's identity before it receives any instructions. Task-specific
parameters live in `task.json` and flow into step guidance via the phase module.

### Fail-fast guards (bootstrap invariants only)

The MCP endpoint validates required `task.json` fields at agent registration:

| Role     | Required fields | Failure if missing                                                      |
| -------- | --------------- | ----------------------------------------------------------------------- |
| scout    | `output_file`   | Step 1 guidance has no assignment -> LLM outputs confused text -> exits |
| planner  | `story_id`      | Malformed paths like `stories//plan/plan.md`                            |
| executor | `story_id`      | Same path issue                                                         |

These checks are intentionally fail-fast because they indicate a broken
parent->child contract (programming/configuration error), not model behavior.

---

## Step-First Workflow

Phase modules in `koan/phases/` define step guidance, system prompts, and
hooks for non-linear flows. The step engine in `koan/web/mcp_endpoint.py`
manages the step counter and dispatches to phase module functions.

Phase modules:

```
koan/phases/
  intake.py
  brief_writer.py
  scout.py
  orchestrator.py
  planner.py
  executor.py
  core_flows.py
  tech_plan.py
  ticket_breakdown.py
  cross_artifact_validation.py
  workflow_orchestrator.py
```

Each phase module exposes:

| Symbol                                  | Kind     | Purpose                              | Default                             |
| --------------------------------------- | -------- | ------------------------------------ | ----------------------------------- |
| `SYSTEM_PROMPT`                         | constant | Role identity and rules              | Required                            |
| `step_guidance(step, ctx)`              | function | Return step instructions             | Required                            |
| `get_next_step(step, ctx)`              | function | Next step or None (done)             | Linear: step+1, None at total_steps |
| `validate_step_completion(step, ctx)`   | function | Pre-condition check before advancing | None (always allow)                 |
| `on_loop_back(from_step, to_step, ctx)` | function | Side effects of backward transitions | no-op                               |

### Step progression state machine

```
koan_complete_step arrives via MCP:
  step == 0       -> step=1, return format_step(step_guidance(1))          [boot transition]
  otherwise       -> validate_step_completion(step)                       [pre-condition check]
                  -> next_step = get_next_step(step)                      [pure: decides where to go]
  next_step is None -> return "Phase complete."                           [done]
  next_step < prev  -> on_loop_back(prev, next_step)                     [side effects of loop]
  next_step != None -> step=next_step, return format_step(step_guidance(next_step))  [advance]
```

### System prompt vs task content

The system prompt establishes **role identity and rules** -- who you are, what
you must/must not do, what output files you produce, what tools you have. It
deliberately omits task details.

Task details arrive as **step guidance** -- the return value of
`koan_complete_step` -- after the LLM has already established the tool-calling
pattern. This separation is load-bearing (see
[architecture pitfalls](./architecture.md#pitfalls)).

### format_step structure

Every step guidance string has the same structure:

```
{title}
{"=".repeat(len(title))}

{instructions}

WHEN DONE: Call koan_complete_step to advance to the next step.
Do NOT call this tool until the work described in this step is finished.
```

The invoke-after directive is always **last** (recency reinforcement).

### The `thoughts` parameter -- escape hatch, not data channel

`thoughts` on `koan_complete_step` is an **escape hatch** for models that
cannot produce both text output and a tool call in the same response.

**The invariant:** `thoughts` must **NEVER** be actively used to capture task
output. No summaries, no reports, no structured data extraction.

Task output goes to files (`findings.md`, `landscape.md`, `plan.md`, etc.).
The driver/parent reads those files after the subagent exits.

---

## Permissions

Default-deny, role-based, enforced at runtime via `check_permission()` in
`koan/lib/permissions.py`.

### READ_TOOLS (always allowed)

`bash`, `read`, `grep`, `glob`, `find`, `ls` -- allowed for all roles. This is
an accepted limitation: `bash` can write files, but distinguishing read-bash
from write-bash is intractable at the permission layer.

### Role permission matrix

| Role             | koan tools                                                                                                                   | write/edit             | notes                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------ |
| **intake**       | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`, `koan_set_confidence`                                      | path-scoped to epicDir | `koan_set_confidence` blocked in step 1 (Extract)                                          |
| **scout**        | `koan_complete_step`                                                                                                         | path-scoped to epicDir | No `koan_ask_question` (no user interaction). No `koan_request_scouts` (no nested scouts). |
| **decomposer**   | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`                                                             | path-scoped to epicDir | --                                                                                         |
| **orchestrator** | `koan_complete_step`, `koan_ask_question`, `koan_select_story`, `koan_complete_story`, `koan_retry_story`, `koan_skip_story` | path-scoped to epicDir | No `koan_request_scouts` -- orchestrator uses bash for verification                        |
| **planner**      | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`                                                             | path-scoped to epicDir | --                                                                                         |
| **executor**     | `koan_complete_step`, `koan_ask_question`                                                                                    | **unrestricted**       | Must modify the actual codebase                                                            |

### Path scoping

Planning roles (intake, scout, decomposer, orchestrator, planner) can only
`write`/`edit` files inside the epic directory. The permission check resolves
both the tool's `path` argument and the epic directory, then verifies the tool
path starts with the epic path.

---

## Model Tiers

### Why 3 tiers instead of per-role configuration

Koan has 6+ roles, but they cluster into 3 capability bands:

| Tier         | Roles                                     | Why this tier                                                    |
| ------------ | ----------------------------------------- | ---------------------------------------------------------------- |
| **strong**   | intake, decomposer, orchestrator, planner | Complex multi-step reasoning                                     |
| **standard** | executor                                  | Code implementation: reliable tool use without deepest reasoning |
| **cheap**    | scout                                     | Narrow codebase investigation: reading files, writing findings   |

The mapping is defined in `koan/config.py`. Adding a new role requires
updating that map.

### Configuration

Model tiers are configured via the web UI at pipeline start. Config is
persisted to `~/.koan/config.json`:

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

### Scout concurrency

`scoutConcurrency` (default: 4) controls how many scout subagents run in
parallel. Increase for faster scouting on machines with ample resources;
decrease to reduce peak memory pressure.

---

## Scout Isolation

Scouts are deliberately constrained compared to other roles:

- **No `koan_ask_question`** -- scouts do not ask questions
- **No `koan_request_scouts`** -- scouts do not spawn nested scouts
- **Three steps** -- investigate -> verify -> report
- **Cheap model** -- scouts use the cheapest available model
- **Parallel execution** -- up to 4 scouts run concurrently
- **Non-fatal failures** -- a failed scout does not abort the parent; its task
  ID is reported in the `failures` array

Scout task parameters (`output_file`, `investigator_role`) live in the scout's
`task.json`. The boot prompt stays minimal; step 1 guidance injects the
parameters.

---

## Subagent Directory Layout

After a subagent runs, its directory contains:

```
{subagent_dir}/
  task.json           # Input: what to do (written by parent before spawn)
  state.json          # Output: audit projection (written by driver)
  events.jsonl        # Output: append-only audit log
  findings.md         # Task output (scouts)
  landscape.md        # Task output (intake)
```

The JSON files have distinct lifecycles per
[architecture.md -- Directory-as-contract](./architecture.md#6-directory-as-contract):

| File         | Writer | Reader | When                       |
| ------------ | ------ | ------ | -------------------------- |
| `task.json`  | Parent | Parent | Once at agent registration |
| `state.json` | Parent | Debug  | Continuous (after events)  |

---

## Web Server Integration

The driver pushes SSE events directly from in-process state transitions. When
a tool call arrives via MCP, the handler emits audit events and pushes SSE
updates to connected browsers in the same call chain.

```
tool call arrives via MCP
  -> handler processes call
  -> emits audit event -> fold -> state.json
  -> pushes SSE event to browsers
  -> returns tool result to subagent
```

Agent registration and deregistration are tracked in the in-process
`AgentState` registry. SSE events for agent lifecycle (`agent-start`,
`agent-complete`) are pushed when agents are registered/deregistered.

Intake sub-phase derivation happens server-side based on step number:

| Step | Pending ask? | Sub-phase      |
| ---- | ------------ | -------------- |
| 1    | --           | `"extract"`    |
| 2    | --           | `"scout"`      |
| 3    | yes          | `"questions"`  |
| 3    | no           | `"deliberate"` |
| 4    | --           | `"reflect"`    |
| 5    | --           | `"synthesize"` |
