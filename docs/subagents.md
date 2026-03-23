# Subagents

How koan spawns, manages, and terminates LLM subagent processes.

> Parent doc: [architecture.md](./architecture.md)

---

## Task Manifest

Every subagent starts as a generic `pi --mode json -p` process with one koan-specific
input: a directory path. The koan extension reads `task.json` from that
directory to learn what kind of subagent it is, what epic it belongs to, and
what work to perform.

### `task.json` schema

The manifest is a discriminated union on the `role` field. Common fields
(`role`, `epicDir`) appear on every variant; role-specific fields are nested
naturally rather than flattened into a shared namespace.

```typescript
// Common to all subagents
interface SubagentTaskBase {
  role: SubagentRole;
  epicDir: string;
}

// Role-specific variants
interface IntakeTask extends SubagentTaskBase {
  role: "intake";
}

interface ScoutTask extends SubagentTaskBase {
  role: "scout";
  question: string; // What to investigate
  outputFile: string; // Where to write findings (relative to subagentDir)
  investigatorRole: string; // Persona for the scout ("security auditor", etc.)
}

interface DecomposerTask extends SubagentTaskBase {
  role: "decomposer";
}

interface OrchestratorTask extends SubagentTaskBase {
  role: "orchestrator";
  stepSequence: "pre-execution" | "post-execution";
  storyId?: string;
}

interface PlannerTask extends SubagentTaskBase {
  role: "planner";
  storyId: string;
}

interface ExecutorTask extends SubagentTaskBase {
  role: "executor";
  storyId: string;
  retryContext?: string; // Failure summary from previous attempt
}

type SubagentTask =
  | IntakeTask
  | ScoutTask
  | DecomposerTask
  | OrchestratorTask
  | PlannerTask
  | ExecutorTask;
```

### Lifecycle

`task.json` is **write-once, read-once**:

1. Parent calls `ensureSubagentDirectory()` → creates the directory
2. Parent writes `task.json` (atomic: tmp + rename)
3. Parent spawns `pi --mode json -p --koan-dir {subagentDir} ...`
4. Child extension reads `task.json` at startup → dispatches to phase
5. `task.json` is never modified after spawn

This makes every subagent directory **self-describing** and **inspectable**
after the fact. `cat task.json` shows exactly what the subagent was asked
to do.

### Why not CLI flags

The previous design passed task configuration as 9 CLI flags
(`--koan-role`, `--koan-epic-dir`, `--koan-subagent-dir`,
`--koan-story-id`, `--koan-step-sequence`, `--koan-retry-context`,
`--koan-scout-question`, `--koan-scout-output-file`, `--koan-scout-role`).

Problems this caused:

| Problem                      | Example                                                                                                                                            |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Flat namespace collision** | `--koan-role` (pipeline role: "scout") vs `--koan-scout-role` (investigator persona: "security auditor") — two unrelated concepts sharing a prefix |
| **Unstructured**             | Role-specific fields mixed with common fields; `extraFlags: string[]` escape hatch needed for extensibility                                        |
| **Size limits**              | `--koan-retry-context` carries multi-paragraph failure summaries — visible in `ps aux`, subject to `ARG_MAX`                                       |
| **Uninspectable**            | After a crash, reconstructing what a subagent was asked to do requires parsing process arguments from logs                                         |
| **Inconsistent**             | Runtime communication uses files (ipc.json); observation uses files (state.json); but task input used CLI args                                     |

---

## Spawn Flow

### Parent side

```
driver: ensureSubagentDirectory(epicDir, label) → subagentDir
driver: write task.json to subagentDir (atomic)
driver: webServer.registerAgent(...)
driver: webServer.trackSubagent(subagentDir, role)
driver: spawnSubagent(task, subagentDir, opts)
          → resolves model for role (3-tier: strong/standard/cheap)
          → builds CLI args: pi --mode json -p -e ext --koan-dir dir [--model model] "boot prompt"
          → spawn("pi", args, { cwd, stdio: ["ignore", "pipe", "pipe"] })
          → captures stdout/stderr to subagentDir/stdout.log, stderr.log
          → parses stdout JSONL for text_delta events → forwards deltas to web server SSE
          → starts IPC responder concurrently (if webServer available)
          → waits for proc.on("close")
          → aborts IPC responder
          → returns { exitCode, stderr, subagentDir }
driver: webServer.clearSubagent()
driver: webServer.completeAgent(id)
driver: checks exitCode, routes to next phase
```

### Child side

```
pi --mode json -p starts with koan extension
koan.ts init:
  → registers --koan-dir flag
  → creates RuntimeContext { epicDir: null, subagentDir: null, onCompleteStep: null }
  → registerAllTools(pi, ctx) — all tools, unconditionally

before_agent_start fires (after _buildRuntime snapshot):
  → reads --koan-dir flag
  → reads task.json from dir → SubagentTask (typed, validated)
  → sets ctx.epicDir = task.epicDir, ctx.subagentDir = dir
  → opens EventLog (audit trail)
  → wires pi event hooks (tool_call, tool_result, turn_end, session_shutdown)
  → dispatchPhase(pi, task, ctx):
      → matches task.role → instantiates phase class → phase.begin()

phase.begin():
  → step = 0, active = true
  → ctx.onCompleteStep = handleStepComplete

LLM receives boot prompt:
  "You are a koan {role} agent. Call koan_complete_step to receive your instructions."
```

### Boot prompt

```
"You are a koan {role} agent. Call koan_complete_step to receive your instructions."
```

One sentence. No task content. The role name is included for primacy — it
anchors the LLM's identity before it receives any instructions. Task-specific
parameters live in `task.json` and flow into step guidance via the phase class.

### Fail-fast guards (bootstrap invariants only)

`dispatchPhase` validates required `task.json` fields before instantiating:

| Role     | Required fields          | Failure if missing                                                    |
| -------- | ------------------------ | --------------------------------------------------------------------- |
| scout    | `question`, `outputFile` | Step 1 guidance has no assignment → LLM outputs confused text → exits |
| planner  | `storyId`                | Malformed paths like `stories//plan/plan.md`                          |
| executor | `storyId`                | Same path issue                                                       |

These checks are intentionally fail-fast because they indicate a broken
parent→child contract (programming/configuration error), not model behavior.

**Boundary:** fail-fast is for unrecoverable conditions only (invariant or
contract violations, unexpected states, or cases with no simple deterministic
local recovery path). Recoverable model-output errors (for example malformed
tool-call JSON/args or schema validation failures) should be surfaced as
normal tool errors (`tool_result` with `isError=true`) so the LLM can retry
in-process, rather than terminating the subagent process.

---

## Step-First Workflow (BasePhase)

`BasePhase` is the abstract superclass for all six phase classes. It manages:

- **Step counter** — starts at 0 (boot state), increments monotonically
- **System prompt injection** — via `before_agent_start` event handler
- **Permission fence** — via `tool_call` event handler (default-deny)
- **Step transition** — via `handleStepComplete()` callback

### Step progression state machine

```
begin() → step=0, active=true, arms ctx.onCompleteStep

LLM calls koan_complete_step:
  step == 0       → step=1, return formatStep(getStepGuidance(1))     [boot transition]
  otherwise       → validateStepCompletion(step)                       [pre-condition check]
                  → nextStep = getNextStep(step)                       [pure: decides where to go]
  nextStep == null → active=false, return null → "Phase complete."    [done]
  nextStep < prev  → onLoopBack(prev, nextStep)                       [side effects of loop]
  nextStep != null → onStepUpdated(nextStep)                          [sync ctx fields]
                  → step=nextStep, return formatStep(getStepGuidance(nextStep))  [advance]
```

`BasePhase` provides three overridable hooks for non-linear flows:

| Hook                           | Purpose                                                                                                                              | Default                            |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- |
| `getNextStep(step)`            | Returns next step number or null (done). **Must be pure.**                                                                           | Linear: step+1, null at totalSteps |
| `onLoopBack(from, to)`         | Side effects of backward transitions: state resets, counter increments, event emission. Async — properly awaited.                    | no-op                              |
| `validateStepCompletion(step)` | Pre-condition check before advancing. Returns null to allow or an error string to block (returned as tool result so LLM can fix it). | null (always allow)                |

`IntakePhase` overrides all three to implement a confidence-gated loop over
steps 2–4. See [intake-loop.md](./intake-loop.md) for details.

Key invariants:

- **`getNextStep()` is pure** — it only returns a step number. Mutation belongs in `onLoopBack()`.
- **`step_transition` is NOT emitted at `begin()`** — it fires when step 1
  guidance is first returned, so the event log reflects when the LLM actually
  begins work.
- **`ctx.onCompleteStep` is nulled on completion** — prevents stale callbacks.
- **Only one phase per RuntimeContext** — `begin()` throws if `ctx.onCompleteStep`
  is already occupied.

### System prompt vs task content

The system prompt (injected via `before_agent_start`) establishes **role
identity and rules** — who you are, what you must/must not do, what output
files you produce, what tools you have. It deliberately omits task details.

Task details arrive as **step guidance** — the return value of
`koan_complete_step` — after the LLM has already established the tool-calling
pattern. This separation is load-bearing (see
[architecture pitfalls](./architecture.md#pitfalls)).

### formatStep structure

Every step guidance string has the same structure:

```
{title}
{"=".repeat(title.length)}

{instructions}

WHEN DONE: Call koan_complete_step with your findings in the `thoughts` parameter.
Do NOT call this tool until the work described in this step is finished.
```

The invoke-after directive is always **last** (recency reinforcement). Steps
that need the LLM to call a domain tool before `koan_complete_step` (e.g.,
`koan_select_story`) can override `invokeAfter`.

### The `thoughts` parameter

`thoughts` is **internal chain-of-thought reasoning only**. It is NOT task
output and MUST NOT be treated as such:

- Task output goes to files (`findings.md`, `context.md`, etc.)
- The driver/parent reads those files after the subagent exits
- `thoughts` exists so models that cannot mix text + tool_call in one response
  (e.g., GPT-5-codex) can still express reasoning while advancing the workflow
- A 500-char prefix of `thoughts` is captured in the audit projection as
  `completionSummary` for scout UI display — this is the only consumer

---

## Permissions

Default-deny, role-based, enforced at runtime via the `tool_call` event handler
in `BasePhase`.

### READ_TOOLS (always allowed)

`bash`, `read`, `grep`, `glob`, `find`, `ls` — allowed for all roles. This is
an accepted limitation: `bash` can write files, but distinguishing read-bash
from write-bash is intractable at the permission layer. Prompt engineering
constrains intended use; enforcement does not.

### Role permission matrix

| Role             | koan tools                                                                                                                   | write/edit             | notes                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------ |
| **intake**       | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`, `koan_set_confidence`                                      | path-scoped to epicDir | `koan_set_confidence` blocked in step 1 (Extract)                                          |
| **scout**        | `koan_complete_step`                                                                                                         | path-scoped to epicDir | No `koan_ask_question` (no user interaction). No `koan_request_scouts` (no nested scouts). |
| **decomposer**   | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`                                                             | path-scoped to epicDir | —                                                                                          |
| **orchestrator** | `koan_complete_step`, `koan_ask_question`, `koan_select_story`, `koan_complete_story`, `koan_retry_story`, `koan_skip_story` | path-scoped to epicDir | No `koan_request_scouts` — orchestrator uses bash for verification                         |
| **planner**      | `koan_complete_step`, `koan_ask_question`, `koan_request_scouts`                                                             | path-scoped to epicDir | —                                                                                          |
| **executor**     | `koan_complete_step`, `koan_ask_question`                                                                                    | **unrestricted**       | Must modify the actual codebase                                                            |

### Path scoping

Planning roles (intake, scout, decomposer, orchestrator, planner) can only
`write`/`edit` files inside the epic directory. The permission check resolves
both the tool's `path` argument and the epic directory, then verifies the tool
path starts with the epic path. If `epicDir` or the path argument is missing,
the write is allowed (cannot scope-check without context).

---

## Model Tiers

### Why 3 tiers instead of per-role configuration

Koan has 6 roles, but they cluster into 3 capability bands. Configuring 3
model names is simpler than 6 and matches the natural grouping:

| Tier         | Roles                                     | Why this tier                                                                                                                                                  |
| ------------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **strong**   | intake, decomposer, orchestrator, planner | Complex multi-step reasoning: investigating ambiguous requirements, splitting work into stories, verifying correctness, producing precise implementation plans |
| **standard** | executor                                  | Code implementation: reliable tool use and file editing without requiring the deepest reasoning                                                                |
| **cheap**    | scout                                     | Narrow codebase investigation: reading files, grepping patterns, writing a focused findings report — no deep reasoning needed                                  |

The mapping is hardcoded in `types.ts` (`ROLE_MODEL_TIER`). Adding a new role
requires updating that map.

### Configuration

Model tiers are configured via the web UI at pipeline start (the **model config
gate** fires before any subagent spawns). The user selects one model per tier.
Config is persisted to `~/.koan/config.json` under the `modelTiers` key:

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

If no config exists or the config is partial, `resolveModelForRole` returns
`undefined` and the `--model` flag is omitted — pi's current active model
becomes the implicit fallback for all roles.

Config is **all-or-nothing**: all 3 tiers must be present. Partial configs
are treated as absent and logged. This prevents a half-configured state where
some roles use intended models and others silently fall back.

### Scout concurrency

`scoutConcurrency` (default: 4) controls how many scout subagents run in
parallel via the bounded pool (`lib/pool.ts`). The pool uses an in-process
semaphore: all scout tasks are submitted to `Promise.all` simultaneously; the
semaphore gates actual execution. Increase this for faster scouting on machines
with ample resources; decrease it to reduce peak memory pressure.

---

## Scout Isolation

Scouts are deliberately constrained compared to other roles:

- **No web server handle** — scouts cannot interact with the user or the UI
- **No `koan_ask_question`** — scouts do not ask questions
- **No `koan_request_scouts`** — scouts do not spawn nested scouts
- **No IPC responder** — since there is no web server, no IPC responder runs
- **Four steps** -- scouts have `totalSteps = 4` (orient -> investigate -> verify -> report). Each step has exactly one cognitive goal, following the "don't give a step multiple cognitive goals" principle from [architecture.md Pitfalls](./architecture.md#pitfalls): separate `koan_complete_step` calls enforce genuinely isolated reasoning and prevent the LLM from sandbagging an earlier step because it already knows a later step is coming
- **Cheap model** — scouts use the cheapest available model
- **Parallel execution** — up to 4 scouts run concurrently via bounded pool
- **Non-fatal failures** — a failed scout does not abort the parent; its task
  ID is reported in the `failures` array and the LLM is told to proceed

Scout task parameters (`question`, `outputFile`, `investigatorRole`) live in
the scout's `task.json`. The boot prompt stays minimal; `ScoutPhase` reads the
task manifest and injects the parameters into step 1 guidance.

---

## Subagent Directory Layout

After a subagent runs, its directory contains:

```
{subagentDir}/
  task.json           # Input: what to do (written by parent before spawn)
  state.json          # Output: audit projection (written by child, polled by parent)
  events.jsonl        # Output: append-only audit log
  ipc.json            # Transient: runtime communication (created/deleted per request)
  stdout.log          # JSONL event stream from pi --mode json -p (structured, not raw text)
  stderr.log          # Captured stderr from pi process
  findings.md         # Task output (scouts)
  context.md          # Task output (intake — conversation, codebase findings, decisions)
```

The three JSON files have distinct lifecycles per
[architecture.md § Directory-as-contract](./architecture.md#6-directory-as-contract):

| File         | Writer | Reader | When                                     |
| ------------ | ------ | ------ | ---------------------------------------- |
| `task.json`  | Parent | Child  | Once at startup                          |
| `state.json` | Child  | Parent | Continuous (50ms polling)                |
| `ipc.json`   | Both   | Both   | Per-request (created, answered, deleted) |

---

## Web Server Integration

The parent registers each subagent with the web server for UI tracking:

```typescript
webServer.registerAgent({ id, name, dir, role, model, parent });
// → starts 50ms polling of audit projection + recent logs
// → SSE "agents" event to browser

webServer.trackSubagent(dir, role, storyId?);
// → starts 50ms polling for "subagent" + "logs" SSE events

// ... subagent runs ...

webServer.clearSubagent();
// → stops tracking timer, emits SSE "subagent-idle"

webServer.completeAgent(id);
// → stops polling, final readProjection, emits SSE "agents" with terminal status
```

**Dual polling for intake agent:** Both `registerAgent()` and
`trackSubagent()` poll at 50ms. `registerAgent` polling derives the intake
sub-phase for the progress bar:

| Step | Pending ask? | Sub-phase      |
| ---- | ------------ | -------------- |
| 1    | —            | `"extract"`    |
| 2    | —            | `"scout"`      |
| 3    | yes          | `"questions"`  |
| 3    | no           | `"deliberate"` |
| 4    | —            | `"reflect"`    |
| 5    | —            | `"synthesize"` |

Steps 2–4 repeat across iterations; the server additionally reads
`intakeConfidence` and `intakeIteration` from the audit projection to populate
the `intake-progress` SSE event for UI visualization.

This derivation is server-side — the server maps step numbers to sub-phase
names. The LLM does not report its sub-phase.
