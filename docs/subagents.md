# Subagents

How koan spawns, manages, and terminates LLM subagent tasks.

> Parent doc: [architecture.md](./architecture.md)

---

## Task Manifest

Every subagent is an asyncio task inside the single backend process. Before
spawning, the driver writes `task.json` to the subagent directory and registers
the agent in the in-process `AppState` registry.

### `task.json` schema

The manifest is a discriminated union on the `role` field. Common fields
(`role`, `run_dir`) appear on every variant; role-specific fields are nested
naturally rather than flattened into a shared namespace.

```json
{
  "role": "intake",
  "run_dir": "/path/to/run"
}
```

Role-specific fields:

| Role           | Additional fields                                                                      |
| -------------- | -------------------------------------------------------------------------------------- |
| `orchestrator` | `project_dir`, `task_description`, `workflow_history: list[{name, phase, started_at}]` |
| `scout`        | `question`, `investigator_role`                                                        |
| `executor`     | `artifacts`, `instructions`                                                            |

`workflow_history` is an append-only list; the most-recent entry is the active
workflow. Executor and scout task.json files do not carry this field.

### Lifecycle

For **executor and scout** subagents, `task.json` is **write-once, read-once**:

1. Driver creates the subagent directory
2. Driver writes `task.json` (atomic: tmp + rename)
3. Driver assigns `agent_id`, registers agent in in-process registry
4. Driver spawns the subagent as an asyncio task via `spawn_subagent`
5. The subagent task calls `_step_phase_handshake_core` to receive step 1
   guidance as its first turn prompt; this is the bootstrap signal
6. `task.json` is never modified after spawn

For the **orchestrator**, `task.json` is written at spawn and then appended
on each `koan_set_workflow` call -- see "Workflow history mutation" below.

This makes every subagent directory **self-describing** and **inspectable**
after the fact. `cat task.json` shows exactly what the subagent was asked
to do (and, for the orchestrator, which workflows it has visited).

### Workflow history mutation

`koan_set_workflow` is the sole writer of subsequent `workflow_history`
entries in the orchestrator's `task.json`. The contract:

- Writes are always atomic (tmp + rename via `write_task_json`).
- Each call appends exactly one `WorkflowHistoryEntry` to the list.
- Readers must tolerate the file growing between reads; the last entry
  is always the active workflow.
- Executor and scout `task.json` files are unaffected -- they do not
  carry the `workflow_history` field.

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
          -> init step engine, event log from task.json
          -> compose toolset for (role, phase) via compose_toolset
driver: spawn_subagent(task, app_state)
          -> creates PydanticAIAgent with composed toolsets
          -> starts asyncio task: run_agent_loop(options, agent_impl, app_state)
          -> loop injects step 1 guidance as first turn prompt
          -> loop drives one turn per agent.iter() call
          -> await task completion
driver: deregister agent_id
driver: check exit code, emit workflow_completed
```

### Agent side (first turn)

```
run_agent_loop starts:
  -> calls _step_phase_handshake_core (step 0 -> 1 transition)
     -> prepends SYSTEM_PROMPT, returns formatted step 1 guidance
  -> injects guidance as first turn prompt
  -> agent.iter() runs the first turn (model request -> tool calls -> terminal text)
  -> first turn reaches End node: AgentState.first_turn_completed = True
  -> resolve_turn_outcome fires: advance to next step or hand back
```

There is no boot prompt. The role identity is carried by the `SYSTEM_PROMPT`
prepended to step 1 guidance. Task-specific parameters live in `task.json`
and flow into step guidance via the phase module.

### Fail-fast guards (bootstrap invariants only)

The driver validates required `task.json` fields at agent registration:

| Role     | Required fields | Failure if missing                                                      |
| -------- | --------------- | ----------------------------------------------------------------------- |
| scout    | `question`      | Step 1 guidance has no assignment -> LLM outputs confused text -> exits |
| executor | `artifacts`     | Executor has no files to read before implementing                       |

These checks are intentionally fail-fast because they indicate a broken
parent->child contract (programming/configuration error), not model behavior.

---

## Step-First Workflow

Phase modules in `koan/phases/` define step guidance, system prompts, and
hooks for non-linear flows. The turn-outcome resolver in `koan/agents/loop.py`
manages the step counter and dispatches to phase module functions.

Phase modules:

```
koan/phases/
  intake.py              # guidance provider: intake phase
  plan_spec.py           # guidance provider: plan phase
  execute.py             # guidance provider: execute phase (general-purpose)
  core_flows.py          # guidance provider: core-flows phase
  tech_plan_spec.py      # guidance provider: tech-plan phase
  milestone_spec.py      # guidance provider: milestone phase
  curation.py            # guidance provider: curation phase
  frame.py               # guidance provider: frame phase
  executor.py            # spawned as separate subagent; implements code changes
  reviewer.py            # spawned as separate subagent; reviews artifacts
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

The turn-outcome resolver (`resolve_turn_outcome`) runs at each end-of-turn:

```
terminal-text turn fires resolve_turn_outcome:
  step == 0  -> step=1, prepend SYSTEM_PROMPT, inject format_step(step_guidance(1))
               [loop bootstrap / phase transition]
  otherwise  -> validate_step_completion(step)              [pre-condition check]
             -> next_step = get_next_step(step)             [pure: decides where to go]
  next_step < prev  -> on_loop_back(prev, next_step)        [side effects of loop]
  next_step != None -> step=next_step, inject format_step(step_guidance(next_step))
                       + any buffered user messages          [advance]
  next_step is None, primary agent  -> hand back to user
  next_step is None, non-primary    -> terminate
```

The actual phase-boundary directive lives in each phase's last-step
`step_guidance()` return value, in the `invoke_after` field. The helper
`terminal_invoke(ctx.next_phase, ctx.suggested_phases)` renders either an
auto-advance directive (`koan_set_phase`) or a hand-back directive
(`koan_suggest_next` then end the turn) depending on whether
`PhaseBinding.next_phase` is bound. See `docs/guided-transitions.md` for the
per-workflow transition tables.

### System prompt vs task content

The system prompt establishes **role identity and rules** -- who you are, what
you must/must not do, what output files you produce, what tools you have. It
deliberately omits task details.

Task details arrive as **step guidance** -- injected as the turn prompt by the
loop at each step. This separation is load-bearing (see
[architecture pitfalls](./architecture.md#pitfalls)).

### format_step structure

Every step guidance string has the same structure:

```
{title}
{"=".repeat(len(title))}

{instructions}

WHEN DONE: end your turn once this step's work is complete -- a turn that
ends with no further tool call advances you to the next step automatically.
Do not end your turn until the step's work is done.
```

The invoke-after directive is always **last** (recency reinforcement). For the
last step of a phase, `terminal_invoke` replaces the default footer with either
an auto-advance directive (`koan_set_phase`) or a hand-back directive
(`koan_suggest_next` then end the turn).

---

## Permissions

Capability restriction is two-layered. `compose_toolset(policy, role)` in
`koan/tools/tool_policy.py` builds vocabulary per **role** (static for the
long-lived orchestrator, so the prompt-cache prefix is never invalidated by a
phase change). A call-time `phase_gate_message` enforces phase-appropriateness
for the orchestrator's phase-conditional tools (`koan_request_executor`,
`bash`, `koan_request_scouts`), returning a recoverable error when used in a
disallowed phase.

Agents should not have access to tools they are never intended to need. A
smaller tool vocabulary reduces misbehavior, token waste, and the chance of
the model drifting toward irrelevant capabilities (plan mode, autonomous
scheduling, subagent spawning) that compete with koan's step-first workflow.

### Per-role built-in tool vocabulary

| Role             | Built-in tools                                                           |
| ---------------- | ------------------------------------------------------------------------ |
| **orchestrator** | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch`, `WebSearch` |
| **executor**     | `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`                          |
| **reviewer**     | `Read`, `Bash`, `Glob`, `Grep` (read-only; no write/edit/scouts)         |
| **scout**        | `Read`, `Bash`, `Glob`, `Grep`                                           |

### Per-role koan tool vocabulary

The allowlist tables in `koan/tools/tool_policy.py` define which koan tools
are composed into each role's toolset. The orchestrator's toolset is
phase-aware -- tools vary by the current phase (`ROLE_PERMISSIONS` joined with
the `_ORCHESTRATOR_SCOUT_PHASES` and `_ORCHESTRATOR_BASH_PHASES` frozensets).
Executor and scout use static sets:

| Role         | koan tools                   | notes                                                      |
| ------------ | ---------------------------- | ---------------------------------------------------------- |
| **scout**    | (none beyond universal read) | No user interaction. No nested scouts. No write.           |
| **executor** | `koan_ask_question`          | Must modify the actual codebase; bash + write unrestricted |

#### READ_TOOLS (always composed for all roles)

`bash`, `read`, `grep`, `glob`, `find`, `ls` -- composed into every role. This
is an accepted limitation: `bash` can write files, but distinguishing read-bash
from write-bash is intractable at the vocabulary layer. Prompt engineering
constrains intended bash use; vocabulary restriction does not.

---

## Executor Subagent

The executor is spawned by the orchestrator via
`koan_request_executor(plan_file?, instructions?)` from within the execute
phase. The tool writes `task.json` for the executor sub-agent and blocks until
the executor exits. The tool result returned to the orchestrator is a
deviation report summarizing what the executor did and any divergences from
the plan. The same plan may be executed any number of times; there is no
re-execution gate. Instructions are required when no `plan_file` is given
(free-form fix runs).

The executor implements code changes in a 3-step workflow:

| Step | Name       | What happens                                                                       |
| ---- | ---------- | ---------------------------------------------------------------------------------- |
| 1    | Comprehend | Immutable handovers are injected; living artifacts are listed for on-demand reads. |
| 2    | Plan       | Identify the specific file edits needed. Do not write code yet.                    |
| 3    | Implement  | Apply changes, verify they match the plan, report what was done.                   |

`task.json` fields for the executor role:

| Field          | Type        | Purpose                                                                                                      |
| -------------- | ----------- | ------------------------------------------------------------------------------------------------------------ |
| `artifacts`    | `list[str]` | Paths relative to `run_dir` that the executor consumes (immutable ones are injected; living ones are listed) |
| `instructions` | `str`       | Free-form context: key decisions, user direction, review findings. Does NOT repeat artifact contents.        |

**Handover injection for the executor.** At spawn, `subagent_candidates(ctx)`
returns the full `executor_artifacts` list from `task.json`. The bootstrap path
then runs `select_immutable_handovers` to filter out living-doc families and
already-injected names, and `preseed_pending_artifacts` wraps each qualifying
file as a `<handoff_artifact name="...">` user message injected before the
step-1 prompt. Living documents (the plan file, `milestones.md`) fall through
the filter and appear instead in the read-on-demand listing produced by
`build_handover_listing`. Step 1 guidance instructs the executor to read the
living artifacts directly; immutable handovers are already in context and need
not be re-read.

The executor has unrestricted `write`/`edit` access -- it must be able to
modify the actual codebase. It may call `koan_ask_question` if it encounters
genuine ambiguity that cannot be resolved from the artifacts and instructions.

## Reviewer Subagent

The reviewer is spawned mechanically by koan as a blocking side-effect of
`koan_artifact_write` for artifact families that have a paired reviewer
(milestones, plan, tech-plan). The reviewer runs in a fresh context, reads
the just-written artifact and any configured upstream artifacts, and returns
freeform findings to the producer as the `koan_artifact_write` tool result.
The reviewer task is "name the artifact, review it" -- there is no predecessor
chain or remediation context. The producer records findings and dispositions
inline in the artifact's `## Review` section via `koan_artifact_edit`.

The reviewer has read-only built-in tools (`Read`, `Bash`, `Glob`, `Grep`)
and no koan write tools. It cannot modify the artifact it reviews.
`koan_ask_question` is not composed into the reviewer toolset; reviewers
return their findings as terminal text and exit.

**Handover injection for the reviewer.** At spawn, `subagent_candidates(ctx)`
returns the reviewer's upstream context set, derived from its charter
(`reviewer_prompt`):

| Charter              | Injected upstream           | Why                                                        |
| -------------------- | --------------------------- | ---------------------------------------------------------- |
| `TECH_PLAN_REVIEWER` | `brief.md`, `core-flows.md` | Tech-plan must respect brief decisions and core flows      |
| `PLAN_REVIEWER`      | `brief.md`, `tech-plan.md`  | Plan must implement brief requirements within tech-plan    |
| `MILESTONE_REVIEWER` | `brief.md`, `tech-plan.md`  | Milestones must decompose work within architectural bounds |

`milestones.md` is listed in the `PLAN_REVIEWER` candidate set but is a
living-doc family -- it passes through `select_immutable_handovers` into the
read-on-demand listing rather than being injected. The `reviewer_target`
(the artifact being reviewed) is always excluded from injection: the reviewer
reads it explicitly via `koan_artifact_read` because it is the focus of the
review, not a standing handover.

---

## Model Tiers

### Why 3 tiers instead of per-role configuration

Koan has 6+ roles, but they cluster into 3 capability bands:

| Tier         | Roles        | Why this tier                                                    |
| ------------ | ------------ | ---------------------------------------------------------------- |
| **strong**   | orchestrator | Complex multi-step reasoning                                     |
| **standard** | executor     | Code implementation: reliable tool use without deepest reasoning |
| **cheap**    | scout        | Narrow codebase investigation: reading files, writing findings   |

The role-to-tier mapping is defined in `koan/config.py`. Adding a new role
requires updating that map.

### Configuration

Model tiers use a profile-based system. Each profile defines three tiers
(`strong`, `standard`, `cheap`), and an active profile is selected at runtime.
Provider credentials come from environment variables; no binary or installation
config is stored. Config is persisted to `~/.koan/config.yaml`:

```yaml
profiles:
  - name: balanced
    tiers:
      strong:
        provider: google
        model: gemini-2.5-pro-preview-06-05
        thinking: disabled
      standard:
        provider: google
        model: gemini-2.5-pro-preview-06-05
        thinking: disabled
      cheap:
        provider: google
        model: gemini-2.5-flash-preview-05-20
        thinking: disabled
active_profile: balanced
scout_concurrency: 8
```

Roles map to tiers (`strong`/`standard`/`cheap`), and tier-to-model bindings
are configured per-profile. Switching profiles changes all model assignments at
once without touching role definitions. Provider availability is checked via
`ProviderStatus` (env-key presence); no binary probe is performed.

### Scout concurrency

`scout_concurrency` (default: 8) controls how many scout subagents run in
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
an in-process tool core runs, it emits audit events and pushes SSE updates to
connected browsers in the same call chain.

```
tool core called by agent (in-process)
  -> core processes call
  -> emits audit event -> fold -> state.json
  -> pushes SSE event to browsers
  -> returns tool result to agent
```

Agent registration and deregistration are tracked in the in-process
`AgentState` registry. SSE events for agent lifecycle (`agent_spawned`,
`agent_exited`) are pushed when agents are registered/deregistered.

Intake sub-phase derivation happens server-side based on step number:

| Step | Sub-phase    |
| ---- | ------------ |
| 1    | `"gather"`   |
| 2    | `"evaluate"` |
| 3    | `"write"`    |
