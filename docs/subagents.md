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
(`role`, `run_dir`, `mcp_url`) appear on every variant; role-specific fields
are nested naturally rather than flattened into a shared namespace.

```json
{
  "role": "intake",
  "run_dir": "/path/to/run",
  "mcp_url": "http://localhost:8420/mcp?agent_id=intake-abc123"
}
```

Role-specific fields:

| Role           | Additional fields                                 |
| -------------- | ------------------------------------------------- |
| `orchestrator` | `project_dir`, `task_description`                 |
| `scout`        | `question`, `investigator_role`                   |
| `executor`     | `artifacts`, `instructions`                       |

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
driver: check exit code, emit workflow_completed
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
| scout    | `question`      | Step 1 guidance has no assignment -> LLM outputs confused text -> exits |
| executor | `artifacts`     | Executor has no files to read before implementing                       |

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
  intake.py              # guidance provider: intake phase
  plan_spec.py           # guidance provider: plan-spec phase
  plan_review.py         # guidance provider: plan-review phase
  execute.py             # guidance provider: execute phase (general-purpose)
  brief_writer.py        # guidance provider: brief-generation phase
  core_flows.py          # guidance provider: core-flows phase
  tech_plan.py           # guidance provider: tech-plan phase
  ticket_breakdown.py    # guidance provider: ticket-breakdown phase
  cross_artifact_validation.py  # guidance provider: cross-artifact-validation and implementation-validation
  executor.py            # spawned as separate subagent; implements code changes
  orchestrator.py        # guidance provider: pre/post execution steps
  scout.py               # spawned as separate subagent; no step guidance role
  format_step.py         # shared formatting utilities
```

Each phase module exposes:

| Symbol                                  | Kind     | Purpose                              | Default                             |
| --------------------------------------- | -------- | ------------------------------------ | ----------------------------------- |
| `SYSTEM_PROMPT`                         | constant | Role identity and rules              | Required                            |
| `SCOPE`                                 | constant | `"general"`, `"plan"`, or `"legacy"` | Required                            |
| `step_guidance(step, ctx)`              | function | Return step instructions             | Required                            |
| `get_next_step(step, ctx)`              | function | Next step or None (done)             | Linear: step+1, None at total_steps |
| `validate_step_completion(step, ctx)`   | function | Pre-condition check before advancing | None (always allow)                 |
| `on_loop_back(from_step, to_step, ctx)` | function | Side effects of backward transitions | no-op                               |

`SCOPE` is metadata, not enforcement. It communicates reusability intent:
`"general"` phases are designed to work across workflows; `"plan"` phases are
specific to the plan workflow; `"legacy"` phases are dead code from an older
pipeline, kept for reference.

### Step progression state machine

```
koan_complete_step arrives via MCP:
  step == 0       -> step=1, prepend SYSTEM_PROMPT, return format_step(step_guidance(1))  [boot/phase transition]
  otherwise       -> validate_step_completion(step)                       [pre-condition check]
                  -> next_step = get_next_step(step)                      [pure: decides where to go]
  next_step is None -> return format_phase_complete(phase, suggested, descriptions) [non-blocking; orchestrator then calls koan_yield]
  next_step < prev  -> on_loop_back(prev, next_step)                     [side effects of loop]
  next_step != None -> step=next_step, return format_step(step_guidance(next_step)) + any buffered user messages  [advance]
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

The orchestrator role uses **phase-aware permissions** — available tools
vary by the current phase. Executor and scout use static permission sets.

**Orchestrator phase-aware permissions:**

| Tool | Available phases |
|------|-----------------|
| `koan_complete_step` | All phases |
| `koan_set_phase` | All phases (blocked mid-story during execution) |
| `koan_ask_question` | All phases |
| `koan_request_scouts` | `intake`, `core-flows`, `tech-plan`, `ticket-breakdown`, `cross-artifact-validation`, `plan-spec`, `plan-review` |
| `koan_request_executor` | `execution`, `execute` |
| `koan_select_story`, `koan_complete_story`, `koan_retry_story`, `koan_skip_story` | `execution` only |
| `write`, `edit` (run_dir scoped) | All phases except `brief-generation` step 1 |
| `bash` | `execution`, `implementation-validation` |

**Other role static permissions:**

| Role           | koan tools                                   | write/edit             | notes                                       |
| -------------- | -------------------------------------------- | ---------------------- | ------------------------------------------- |
| **scout**      | `koan_complete_step`                         | none                   | No user interaction. No nested scouts. No file writing. |
| **executor**   | `koan_complete_step`, `koan_ask_question`    | **unrestricted**       | Must modify the actual codebase             |

### Path scoping

Planning roles (orchestrator, scout) can only `write`/`edit` files inside the
run directory. The permission check resolves both the tool's `path` argument
and the run directory, then verifies the tool path starts with the run path.

---

## Executor Subagent

The executor is spawned by the orchestrator via `koan_request_executor`. It
receives structured inputs via `task.json` and implements code changes in a
3-step workflow:

| Step | Name | What happens |
|------|------|--------------|
| 1 | Comprehend | Read all artifacts listed in `task.json`. Understand the plan and codebase context. |
| 2 | Plan | Identify the specific file edits needed. Do not write code yet. |
| 3 | Implement | Apply changes, verify they match the plan, report what was done. |

`task.json` fields for the executor role:

| Field | Type | Purpose |
|-------|------|---------|
| `artifacts` | `list[str]` | Paths relative to `run_dir` that the executor must read before coding |
| `instructions` | `str` | Free-form context: key decisions, user direction, review findings. Does NOT repeat artifact contents. |

The executor has unrestricted `write`/`edit` access — it must be able to modify
the actual codebase. It may call `koan_ask_question` if it encounters genuine
ambiguity that cannot be resolved from the artifacts and instructions.

`koan_request_executor` blocks until the executor process exits. The orchestrator
receives a success/failure summary and reports it to the user at the execute phase boundary.

---

## Model Tiers

### Why 3 tiers instead of per-role configuration

Koan has 6+ roles, but they cluster into 3 capability bands:

| Tier         | Roles                          | Why this tier                                                    |
| ------------ | ------------------------------ | ---------------------------------------------------------------- |
| **strong**   | orchestrator                   | Complex multi-step reasoning                                     |
| **standard** | executor                       | Code implementation: reliable tool use without deepest reasoning |
| **cheap**    | scout                          | Narrow codebase investigation: reading files, writing findings   |

The role-to-tier mapping is defined in `koan/config.py`. Adding a new role
requires updating that map.

### Configuration

Model tiers use a profile-based system. Each profile defines three tiers
(`strong`, `standard`, `cheap`), and an active profile is selected at runtime.
Agent installations declare available runners and binaries. Config is persisted
to `~/.koan/config.json`:

```json
{
  "agentInstallations": [
    { "alias": "claude-sonnet", "runnerType": "claude", "binary": "claude", "extraArgs": [] }
  ],
  "profiles": [
    {
      "name": "balanced",
      "tiers": {
        "strong":   { "runnerType": "claude", "model": "claude-sonnet-4-5", "thinking": "disabled" },
        "standard": { "runnerType": "claude", "model": "claude-sonnet-4-5", "thinking": "disabled" },
        "cheap":    { "runnerType": "claude", "model": "claude-haiku-4-5",  "thinking": "disabled" }
      }
    }
  ],
  "activeProfile": "balanced",
  "scoutConcurrency": 8
}
```

Roles map to tiers (`strong`/`standard`/`cheap`), and tier-to-model bindings
are configured per-profile. Switching profiles changes all model assignments at
once without touching role definitions.

### Scout concurrency

`scoutConcurrency` (default: 8) controls how many scout subagents run in
parallel. Increase for faster scouting on machines with ample resources;
decrease to reduce peak memory pressure.

---

## Scout Isolation

Scouts are deliberately constrained compared to other roles:

- **No `koan_ask_question`** -- scouts do not ask questions
- **No `koan_request_scouts`** -- scouts do not spawn nested scouts
- **No file writing** -- scouts have no `write`/`edit` access
- **Three steps** -- investigate -> verify -> report
- **Cheap model** -- scouts use the cheapest available model
- **Parallel execution** -- up to 8 scouts run concurrently
- **Non-fatal failures** -- a failed scout does not abort the parent; its task
  ID is reported in the `failures` array

Scout task parameters (`question`, `investigator_role`) live in the scout's
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
`AgentState` registry. SSE events for agent lifecycle (`agent_spawned`,
`agent_exited`) are pushed when agents are registered/deregistered.

Intake sub-phase derivation happens server-side based on step number:

| Step | Sub-phase     |
| ---- | ------------- |
| 1    | `"gather"`    |
| 2    | `"evaluate"`  |
| 3    | `"write"`     |
