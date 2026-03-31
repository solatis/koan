# Koan Epoch: Refactoring Plan

> **Authoritative rewrite spec: §11 (2026-03-11), amended by §12
> (2026-03-12).** Sections §1–§10 are historical context. §11 contains
> the resolved decisions from the full codebase analysis session. §12
> documents scope/lifecycle mismatches discovered post-implementation
> and the fixes required. Implementers should read §11 first, then §12
> for the outstanding fixes, then reference earlier sections only for
> background understanding.

This document describes the refactoring of koan from its current monolithic
plan-then-review pipeline into a spec-driven execution orchestrator for pi.
**Backwards compatibility with the current plan schema, phase structure, and QR
block pattern is not a concern.** This is a clean-sheet redesign of the
workflow, retaining the infrastructure that works and discarding the
architecture that doesn't.

---

## 1. Terminology

### Domain model

Three terms describe the work.

- **Epic**: The top-level decomposition of user intent into stories. Contains
  the spec, captured decisions, and story sketches. One epic per user request.
- **Story**: A coherent unit of work — something a senior engineer would
  consider one PR. Each story gets its own plan when it's time to execute.
- **Plan**: The detailed implementation plan for a single story, created
  just-in-time when the story is selected for execution. Contains file-level
  change descriptions, curated code context, and verification checks.

### System roles

Seven roles operate on the domain model. One is deterministic code; six are
LLM subagents.

- **Driver**: The deterministic TypeScript process that manages subagent
  lifecycle. Spawns subagents, polls for completion, relays IPC, reads state
  files, decides what to spawn next. No LLM reasoning. The compiler analogy:
  gcc's driver program invokes preprocessor, compiler, assembler, linker in
  sequence — it doesn't do the work itself. Replaces the current `session.ts`.
- **Intake**: A strong-model subagent that reads the conversation, extracts
  structured context, identifies gaps, and interactively resolves ambiguities
  with the user. Produces `context.md` and `decisions.md`.
- **Scout**: A cheap-model subagent that answers one narrow codebase question
  and writes its raw findings to a markdown file. No interpretation, no
  recommendations. Multiple scouts run in parallel via `pool()`. Each scout
  writes a single output file (e.g., `scouts/{scout-id}.md`); the driver
  collects file paths after `pool()` completes and passes them to the
  consuming subagent (decomposer or planner).
- **Decomposer**: A strong-model subagent that splits the epic into story
  sketches. Receives intake output and scout reports. Produces `epic.md` and
  per-story `story.md` files.
- **Orchestrator**: A strong-model subagent responsible for decisions at
  critical points during execution. The driver spawns it with different step
  sequences depending on the decision point: pre-execution analysis (dependency
  mapping, sequencing) and post-execution assessment (verification, learning
  propagation, deviation classification, next-story selection). Reads state
  from files, writes decisions to files. Each invocation is a fresh subagent
  spawn with a clean context window — the orchestrator is not a long-running
  process that accumulates context across stories. The driver spawns it, it
  reads the current state files, it writes decisions, it exits. The next time
  the driver needs the orchestrator, it spawns a new one. This is a
  deliberate architectural property: Koan's subagent model gives every
  invocation a clean context by design.
- **Planner**: A strong-model subagent that produces the detail plan for a
  single story just-in-time. Receives the story sketch, decisions, and scout
  reports. Produces `plan.md`, `context.md`, and `verify.md`.
- **Executor**: The only subagent that writes code. Receives `plan.md` and
  `context.md`, implements the plan. Uses a standard-tier model.

All six LLM roles use the step-based phase class lifecycle and get their own
EventLog. The driver controls when each role runs and what happens with its
output (INV-1).

### Driver vs orchestrator boundary

The driver and orchestrator are the only two actors that influence workflow
progression — every other role (intake, scout, decomposer, planner, executor)
has a clear, scoped job that doesn't affect what happens next. The orchestrator
is the only agent whose decisions guide the workflow: which story to work on,
whether a story passed verification, whether to retry or escalate. The other
five LLM roles produce artifacts and exit. Their boundaries are obvious.

The driver/orchestrator boundary is the one point of common misunderstanding,
because both actors influence "what happens next" but through fundamentally
different mechanisms. The decision rule:

> The driver reads STATE (status values, exit codes, file existence) and
> applies RULES. The orchestrator reads CONTENT (artifacts, code, verification
> results) and applies JUDGMENT.

#### Seems mechanical, actually requires judgment → orchestrator

**Running verify.md checks.** ✅ Orchestrator reads `verify.md`, runs checks
via `bash`, interprets results, calls `koan_complete_story` or
`koan_retry_story`. ❌ Driver parses `verify.md` and runs the checks — it
doesn't know _which_ commands to run (planning artifact) or whether "2 tests
failed" is blocking or expected.

**Selecting the next story.** ✅ Orchestrator reads dependency graph in
`epic.md`, checks which stories are `done`, calls `koan_select_story`.
❌ Driver sorts stories by dependency order — dependency analysis requires
reading artifact content, which is judgment.

**Assessing partial verification (8/10 checks pass, 2 fail).** ✅ Orchestrator
examines the 2 failures in context: "CSS test is flaky; API test reveals real
bug" → `koan_retry_story` citing the real issue. ❌ Driver counts pass/fail
ratio and applies a threshold — it has no notion of failure severity.

#### Seems like a decision, actually a deterministic rule → driver

**Retry budget exhaustion.** ✅ Driver decrements retry counter after each
`retry` status; at zero, sets status to `escalated` — orchestrator is never
spawned. ❌ Orchestrator checks "how many retries have we done?" — it can't,
fresh context each invocation.

**Epic completion.** ✅ Driver reads all `state.json` files, finds every story
`done` or `skipped`, reports completion. ❌ Orchestrator calls
`koan_complete_epic` — no such tool, driver infers from aggregate state.

**Scout failure during planning.** ✅ Driver records failures via `pool()`,
proceeds with partial results. ❌ Orchestrator is consulted — scouts are
part of the fixed cycle, not a judgment call.

#### Seems like it needs a tool, actually uses `write` → orchestrator

**Propagating learnings.** ✅ Orchestrator uses `write` to update `story.md`
files and append to `decisions.md` with `[autonomous]` marker. ❌ Driver
detects S-001 modified auth files and triggers updates — it doesn't read
code or understand what changed.

**Splitting a story mid-epic.** ✅ Orchestrator uses `write` to create new
`story.md` files, calls `koan_skip_story` on the original. ❌ Orchestrator
calls `koan_create_story(...)` — no such tool; artifact creation uses `write`,
tools exist only for state transitions the driver acts on.

#### Split responsibility — both actors, different concerns

**Retry verdict.** ✅ Orchestrator (qualitative): "this failure is fixable" →
`koan_retry_story`. ✅ Driver (quantitative): "budget exhausted" → force
`escalated`. ❌ Either actor does both — orchestrator doesn't count retries,
driver doesn't judge failure severity.

**Plan-reality mismatch during execution.** ✅ Simple clarification → executor
asks user via `koan_ask_question` in-place. ✅ Fundamental spec error →
executor exits, orchestrator (post-execution) classifies deviation, calls
`koan_escalate`. ❌ Orchestrator spawned mid-execution — it runs at cycle
boundaries only. ❌ Driver analyzes executor output — it reads exit codes and
status values, nothing else.

### Model tiers

Three model tiers allocate cost to capability.

- **Strong**: High-capability reasoning models (e.g., Opus, o3). Used where
  judgment quality is critical: intake, decomposition, orchestration, planning.
- **Standard**: Competent coding models (e.g., Sonnet, GPT-4o). Used where
  the task is well-specified and the model follows instructions rather than
  making architectural decisions: execution.
- **Cheap**: Fast, low-cost models (e.g., Haiku, Grok-fast). Used where the
  task is narrow and mechanical: scouting.

---

## 2. What the End System Looks Like

### 2.1 One-sentence summary

Koan becomes a two-phase system: an epic creation pipeline that front-loads
spec clarity and story decomposition, followed by a JIT execution loop where
the orchestrator sequences story planning, execution, and verification one
story at a time against the _current_ codebase.

### 2.2 The two-phase architecture

**Phase A: Epic Creation** (driver-managed, no orchestrator)

The driver spawns dedicated subagents in sequence: intake (interactive),
decomposer with scouts, then the spec review gate.

```
User prompt ─► Intake ─► Epic Decomposition ─► Story Sketches
                 │                                    │
                 │ (interactive: asks                  ▼
                 │  user questions)          Spec Review Gate
                 ▼
            context.md
          + decisions.md
```

**Phase B: Epic Execution** (orchestrator-managed)

The driver spawns the orchestrator at each decision point, reads its output,
then deterministically spawns the next subagent.

```
┌────────────────────────────────────────────────────────────┐
│  Driver spawns orchestrator (pre-execution step sequence)  │
│  → selects first story, writes state files                 │
│                                                            │
│  Driver spawns planner (+ scouts) for selected story       │
│  → produces plan.md + context.md + verify.md               │
│                                                            │
│  Driver spawns executor                                    │
│  → implements the plan                                     │
│                                                            │
│  Driver spawns orchestrator (post-execution step sequence) │
│  → verifies, propagates learnings, selects next story      │
│                                                            │
│  Driver reads state files → loops or completes             │
└────────────────────────────────────────────────────────────┘
```

### 2.3 Artifacts produced

All state lives under `~/.koan/state/`. Nesting captures relationships —
no cross-reference IDs needed.

```
~/.koan/state/epics/{epic-id}/
├── context.md          # conversation summary, indices, testing strategy
├── decisions.md        # explicit decisions from intake + [autonomous] decisions
├── epic.md             # overview + story list + sequencing
├── scouts/             # decomposition-phase scout output files
│   └── {scout-id}.md   # raw findings for one codebase question
├── stories/
│   ├── {story-id}/
│   │   ├── story.md    # story sketch (scope, acceptance, deps)
│   │   ├── status.md   # execution state, outcome, notes
│   │   ├── scouts/     # per-story scout output files (JIT planning phase)
│   │   │   └── {scout-id}.md
│   │   └── plan/
│   │       ├── plan.md     # file-level implementation plan (JIT)
│   │       ├── context.md  # curated code snippets for executor
│   │       └── verify.md   # acceptance checks + test strategy
│   └── ...
└── subagents/          # per-subagent EventLog dirs (runtime)
```

All planning artifacts are markdown. Per-subagent EventLog directories
(`events.jsonl` + `state.json`) live under `subagents/`.

**Artifact flow by phase:**

| Phase                 | Reads                                                    | Writes                                                                                    |
| --------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Intake                | `conversation.jsonl`                                     | `context.md`, `decisions.md`                                                              |
| Scouts (decomp)       | Codebase (via READ_TOOLS)                                | `scouts/{scout-id}.md`                                                                    |
| Decomposition         | `context.md`, `decisions.md`, `scouts/*.md`              | `epic.md`, per-story `story.md`                                                           |
| Spec review           | `epic.md`, `story.md` files                              | User edits to `epic.md`, `story.md`                                                       |
| Pre-execution (orch)  | `epic.md`, `decisions.md`                                | `status.md` (via `koan_select_story`)                                                     |
| Scouts (per-story)    | Codebase (via READ_TOOLS)                                | `stories/{id}/scouts/{scout-id}.md`                                                       |
| Detail-plan           | `story.md`, `decisions.md`, `scouts/*.md`                | `plan/plan.md`, `plan/context.md`, `plan/verify.md`                                       |
| Execute               | `plan/plan.md`, `plan/context.md`                        | Codebase changes                                                                          |
| Post-execution (orch) | `verify.md`, `plan.md`, `status.md`, git diff, `epic.md` | `status.md` (via tools), `story.md` (remaining), `decisions.md` ([autonomous]), `epic.md` |

Each phase reads only the artifacts produced by prior phases. The executor is
the only role that writes to the codebase; all other roles write to the epic
directory.

### 2.4 Human interaction model

One mandatory human gate: **spec review**, after epic creation produces story
sketches. The user confirms scope, adjusts sketches, adds or removes stories.

After that, execution is autonomous by default. The system escalates to the
human only when:

- **Out-of-plan deviation**: execution revealed something that requires the
  original spec to change. The escalation presents: problem description,
  candidate solutions, recommended solution, custom response option.
- **Verification failure**: a story fails verification after the retry budget
  (default 2 retries).
- **Unresolvable ambiguity**: any subagent encounters something it cannot
  resolve without human input.

Everything else is in-plan — the orchestrator handles it autonomously. The
classification test: does this change what the user asked for, or just how we
deliver it? In-plan adjustments (refine acceptance criteria, split/merge
stories, reorder execution) are recorded in `decisions.md` with an
`[autonomous]` marker for traceability.

**Mid-execution escalation via `koan_ask_question`.** All subagents have access
to the existing `koan_ask_question` tool, which uses file-based IPC to pause
execution, present a question to the user in the parent session, and resume
after the user responds. This means any subagent — intake, planner, executor,
orchestrator — can ask the human a focused question at the point where the
ambiguity arises, without aborting its session. The subagent writes the
question to an IPC file, polls until the parent writes back an answer, and
continues with the response in its context window. This eliminates the need
for complex checkpoint/resume mechanisms: instead of saving state and
restarting, the agent simply waits for the answer and proceeds.

### 2.5 Model allocation

| Role         | Model tier | Why                                        |
| ------------ | ---------- | ------------------------------------------ |
| Intake       | Strong     | Reasoning about gaps, not summarization    |
| Decomposer   | Strong     | Architectural judgment                     |
| Scout        | Cheap      | File discovery, pattern gathering          |
| Orchestrator | Strong     | Cross-story reasoning, verification        |
| Planner      | Strong     | Synthesizes scout findings into plan       |
| Executor     | Standard   | Well-specified task, instruction-following |

Cheap models gather, strong models decide, standard models execute.

### 2.6 Story state machine

Each story transitions through a fixed set of states. The driver manages
intermediate transitions by writing to `state.json`; the orchestrator's
tools write terminal/routing states to both `state.json` (for the driver)
and `status.md` (for LLMs). The driver reads `state.json` to determine
next actions.

```
pending ──[koan_select_story]──► selected
   │                                │
   │                          (driver: fixed)
   │                                │
   │                         planning ──► executing ──► verifying
   │                                                      │
   │                              ┌───────────────────────┤
   │                              │           │           │
   │                    [complete_story]  [retry_story]  [escalate]
   │                              │           │           │
   │                              ▼           ▼           ▼
   │                            done        retry     escalated
   │                                          │           │
   │                                    (driver: re-     (driver:
   │                                     spawn exec)    ask user)
   │                                          │           │
   │                                     executing    (user responds)
   │                                          │           │
   │                                       verifying    verifying
   │
   └──[koan_skip_story]──► skipped
```

States in brackets (`[tool_name]`) are orchestrator tool calls. States
marked `(driver: ...)` are deterministic driver transitions.

The `planning`, `executing`, and `verifying` intermediate states are
managed by the driver — it writes them to `state.json` as it spawns
the corresponding subagents. The orchestrator's tools write terminal or
routing states (`selected`, `done`, `retry`, `escalated`, `skipped`) to
both `state.json` and `status.md`.

### 2.7 Tool inventory

The driver owns the fixed per-story cycle (plan → execute → verify). The
orchestrator owns judgment calls at cycle boundaries. A tool exists only
when the driver must act on the result — artifact modifications (updating
`story.md`, appending to `decisions.md`) use the existing `write` tool.

**Design principle**: each tool is atomic — it transitions exactly one
entity to exactly one new state.

| Tool                  | Purpose                                                 | Parameters                                                                           | State Transition                         |
| --------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------- |
| `koan_select_story`   | Pick which story to work on next                        | `story_id: string`                                                                   | Story: `pending` or `retry` → `selected` |
| `koan_complete_story` | Mark a story as verified and done                       | `story_id: string`                                                                   | Story: `verifying` → `done`              |
| `koan_retry_story`    | Mark a story for re-execution after failed verification | `story_id: string`, `failure_summary: string`                                        | Story: `verifying` → `retry`             |
| `koan_escalate`       | Flag a story for human decision                         | `story_id: string`, `problem: string`, `candidates: string[]`, `recommended: string` | Story: `verifying` → `escalated`         |
| `koan_skip_story`     | Mark a pending story as no longer needed                | `story_id: string`, `reason: string`                                                 | Story: `pending` → `skipped`             |
| `koan_complete_step`  | (existing) Advance to next step within a phase          | `thoughts?: string`                                                                  | Internal step counter                    |
| `koan_ask_question`   | (existing) Pause and ask the user a question            | `questions: QuestionItem[]`                                                          | None (synchronous)                       |

**What's not here and why:**

- No `launch_scouts` — the driver spawns scouts as part of the fixed
  planner workflow. Not an orchestrator decision.
- No `request_plan_detail` — the driver spawns the planner after
  `koan_select_story`. Fixed sequence.
- No `trigger_review` — the driver spawns the orchestrator (post-execution
  step sequence) after the executor exits. Fixed sequence.
- No `update_story` — the orchestrator uses the `write` tool to modify
  `story.md` files directly. Not a state transition the driver acts on.
- No `complete_epic` — the driver infers epic completion from state: all
  stories are `done` or `skipped`. No explicit signal needed.

**Permission map for the orchestrator:**

```typescript
[
  "orchestrator",
  new Set([
    "koan_complete_step",
    "koan_ask_question",
    "koan_select_story",
    "koan_complete_story",
    "koan_retry_story",
    "koan_escalate",
    "koan_skip_story",
  ]),
];
```

Plus READ_TOOLS (always allowed) and Write scoped to the epic directory
(planning subagent tier).

### 2.8 Driver state management

The driver reads state, not signals. After the orchestrator exits, the
driver reads `state.json` for each story and applies deterministic rules:

- Any story with status `retry`? → Re-spawn executor (decrement retry
  budget; if exhausted, set status to `escalated` and present to user).
- Any story with status `escalated`? → Present escalation to user, pause.
- Any story with status `selected`? → Spawn planner for it.
- All stories `done` or `skipped`? → Epic complete.
- None of the above? → Error (orchestrator exited without making a
  routing decision).

Structured execution state (retry counts, current phase within the
per-story cycle, etc.) lives in `state.json` alongside `status.md`.
The driver reads only JSON; LLMs read only markdown. Orchestrator tools
bridge both by writing to both formats atomically (see §9.1).

### 2.9 Responsibility map

| Action                                      | Actor                    | Tool / Mechanism                                                                                                                     | Trigger                                                     |
| ------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| Export conversation                         | Driver                   | `exportConversation()`                                                                                                               | User invokes `koan_plan`                                    |
| Create epic directory                       | Driver                   | `fs.mkdir()`                                                                                                                         | After export                                                |
| Context capture + elicitation               | Intake                   | `koan_complete_step`, `koan_ask_question`, `write`                                                                                   | Driver spawns after directory creation                      |
| Codebase scouting (decomp)                  | Scouts (parallel)        | READ_TOOLS, `koan_complete_step`, `write`                                                                                            | Driver spawns after intake exits                            |
| Epic decomposition                          | Decomposer               | `koan_complete_step`, `write`                                                                                                        | Driver spawns after scouts complete                         |
| Spec review                                 | User via driver UI       | Approve/edit/remove widget                                                                                                           | Driver presents after decomposer exits                      |
| Dependency analysis + first story selection | Orchestrator (pre-exec)  | `koan_select_story`, `koan_complete_step`, `write`                                                                                   | Driver spawns after user approves spec                      |
| Codebase scouting (per-story)               | Scouts (parallel)        | READ_TOOLS, `koan_complete_step`, `write`                                                                                            | Driver spawns after reading `selected` status               |
| Produce detail plan                         | Planner                  | `koan_complete_step`, `write`                                                                                                        | Driver spawns after scouts complete                         |
| Implement story                             | Executor                 | WRITE_TOOLS, `koan_complete_step`, `koan_ask_question`                                                                               | Driver spawns after planner exits                           |
| Verify + assess + propagate + select next   | Orchestrator (post-exec) | `koan_complete_story` / `koan_retry_story` / `koan_escalate`, `koan_select_story` / `koan_skip_story`, `write`, `koan_complete_step` | Driver spawns after executor exits                          |
| Re-execute on retry                         | Executor                 | Same as implement                                                                                                                    | Driver reads `retry` status, re-spawns with failure context |
| Present escalation                          | Driver                   | IPC / ask UI                                                                                                                         | Driver reads `escalated` status                             |
| Learning propagation                        | Orchestrator (post-exec) | `write` (modifies `story.md`, `decisions.md`)                                                                                        | During post-execution steps                                 |
| Epic completion                             | Driver                   | Detects all stories `done`/`skipped`                                                                                                 | After orchestrator exits without selecting a new story      |

---

## 3. What We Keep

**Inversion of control (INV-1).** The driver manages all workflow transitions.
LLM subagents are workers within phases, never coordinators across phases.

**Step-based subagent lifecycle.** All subagents use the step-based phase class
pattern: constructor registers event hooks, `begin()` dispatches,
`handleStepComplete()` advances steps. Output validation is the
orchestrator's responsibility (post-execution verification), not a method
on the phase class.

**Self-loading extension pattern (AD-2).** Same `extensions/koan.ts` serves
driver and subagent modes via CLI flag detection.

**Tool-call-driven step transitions (AD-4).** `koan_complete_step` with
`thoughts` parameter, the invoke-after pattern (AD-7), and the two-part
gate remain.

**Default-deny tool permissions (AD-13).** Centralized permission map, unknown
tools blocked. Extended with two new tiers: planning subagents get Write
scoped to the epic directory (cannot modify the codebase), executor subagents
get full WRITE_TOOLS to the codebase. `koan_ask_question` is available to all
subagent roles except scout — scouts are narrow-scope investigators that
should not need user interaction. All other roles can escalate to the human
mid-execution.

**Disk-backed mutations (AD-14).** Immediate persistence via atomic writes,
extended to the new markdown file structure.

**Subagent spawning and pool infrastructure.** `spawnSubagent()`, its helpers,
and `pool()` for parallel execution are reused as-is. New roles are new spawn
functions delegating to the same core.

**Per-subagent EventLog.** `EventLog`, `readProjection()`, `readRecentLogs()`
reused. Every subagent gets its own log directory under `{epic-dir}/subagents/`.

**IPC mechanism and `koan_ask_question`.** `readIpcFile()`, `writeIpcFile()`,
`pollWithIpcDetection()` reused. The `koan_ask_question` tool — which lets any
subagent pause, present a question to the user, and resume with the answer —
carries over as the universal mid-execution escalation mechanism. Ask UI
components (`askSingleQuestionWithInlineNote`, `askQuestionsWithTabs`) carry
over.

**Widget UI primitives.** `WidgetController` and rendering primitives reused
as building blocks. Layout and content get a full redesign.

**Agent prompts as embedded TypeScript.** Loading mechanism preserved; content
changes entirely for new roles.

**Convention resources, model config, conversation export.** All preserved.

---

## 4. What We Discard

**The monolithic plan.json schema.** The entire `Plan` type hierarchy
(`Milestone`, `CodeIntent`, `CodeChange`, `Wave`, `DiagramGraph`, etc.) is
removed. Replaced by per-story markdown files and `decisions.md` at the epic
level. The `PlanningContext` concept (`Decision`, `RejectedAlternative`,
`Risk`, `InvisibleKnowledge`) migrates to `decisions.md`.

**The wave concept.** Waves grouped milestones into execution batches — an
ordering layer on top of the dependency graph. In the new system, execution
order is determined by the orchestrator's dependency analysis at runtime, one
story at a time. There is no need for a static grouping structure: the
orchestrator selects the next story based on what's unblocked after each
completion. Waves and all associated tools (`koan_add_wave`,
`koan_set_wave_milestones`) are removed.

**The three-phase sequential pipeline.** plan-design → plan-code → plan-docs
removed. Each story's detail-plan produces a single `plan.md` with everything
needed for execution.

**The QR decompose/verify/fix block.** The entire QR pipeline removed — this
was the single largest cost driver (6 parallel reviewers × 3 phases × up to 5
fix iterations = up to 90 subagent processes per plan). Replaced by per-story
verification managed by the orchestrator, with a per-story retry budget
(default 2).

**The QR severity model.** `qr-severity.ts`, `MAX_FIX_ITERATIONS`,
`qrPassesAtIteration()` removed. Replaced by pass/fail/escalate.

**The 44+ plan mutation tools.** All plan getter/setter/mutate tools removed.
Planning subagents now write files directly using the Write tool, scoped to the
epic directory.

**Plan validation and cross-reference checking.** `validate.ts` removed. The
new markdown-per-story structure has no cross-references to validate.

**Plan rendering.** `render.ts` removed. Plans are already markdown.

**The architect/developer/technical-writer/qr-decomposer/reviewer roles.** All
five current agent roles replaced by the six roles in section 1.

**The 6-step architect workflow.** The fixed exploration → analysis → approach →
assumptions → milestones → writing sequence (AD-16) removed. Intake and
decomposition have their own step structures.

**Session concept.** `session.ts` and the `Session` interface removed. The
driver replaces the session.

---

## 5. Workflow and Role Responsibilities

### 5.1 Triggering

The user asks pi to plan something complex, `koan_plan` is invoked. The
conversation is exported to `conversation.jsonl`. The epic directory is
created under `~/.koan/state/epics/{epic-id}/`.

### 5.2 Intake

**Input**: `conversation.jsonl`.
**Output**: `context.md` and `decisions.md`.
**Steps**: Multi-step, interactive.

The intake subagent reads the full conversation and performs two tasks in a
single session. First, it extracts structure into `context.md` with five
sections: topic index, file references, decisions already made, constraints
stated, and unresolved questions. Second, it reviews the structured summary
for gaps — ambiguities, unstated assumptions, conflicting statements, and
missing testing strategy — and interactively asks the user to resolve them
via the existing ask UI (relayed through IPC).

Questions are multiple-choice where possible, with a free-text escape hatch.
Maximum 8 questions. If the conversation was thorough, there may be zero
questions and the interactive step is skipped. If the user dismisses
questions, the intake subagent records "deferred to agent judgment" for each.

User answers are written to `decisions.md` — a permanent record traceable to
specific conversation turns or intake questions.

The intake subagent must NOT infer decisions that weren't explicitly stated or
confirmed, add architectural opinions, summarize code (it hasn't read any),
or produce implementation recommendations.

**Prompt gist**: "Read the conversation. Extract what was decided, what files
were mentioned, what constraints were stated, and what was left ambiguous.
Then identify gaps that need answers before planning can begin — including
testing strategy. For each gap, formulate one focused question with concrete
options."

### 5.3 Epic Decomposition

**Input**: `context.md`, `decisions.md`, the codebase (via scouts).
**Output**: `epic.md` + per-story `stories/{story-id}/story.md`.
**Steps**: Fan out scouts, synthesize into sketches.

The driver spawns scouts in parallel via `pool()` to gather codebase
information. Each scout answers one narrow question and writes its findings
to a markdown file under `scouts/` (e.g., `scouts/scout-001.md`). The driver
collects the output file paths after `pool()` completes, then spawns the
decomposer (strong model) with `context.md`, `decisions.md`, and the scout
output file paths. The decomposer synthesizes scout findings into story
sketches.

A sketch describes what the story does, why it exists, which files are likely
affected, what it depends on, and acceptance criteria. A sketch is NOT a
detailed implementation plan — it is comparable to a JIRA ticket.

Example `epic.md` structure:

```markdown
# <Epic Title>

## Overview

<one-paragraph problem + approach summary>

## Stories

### S-001: Auth Provider Integration

OAuth2 with Google and GitHub via next-auth. Leaf — no dependencies.
Files likely affected: src/lib/auth.ts, src/app/api/auth/[...nextauth]/route.ts
Acceptance: OAuth flow completes for both providers, tokens stored in session.

### S-002: Protected Route Middleware

Depends on: S-001
...

## Sequencing

S-001 first (leaf). S-002 and S-003 after S-001, independent of each other.
```

The decomposer must NOT write implementation details, make decisions that
belong to the user, or over-decompose (a 3-file change should not become 3
stories).

**Prompt gist**: "Decompose this feature request into independent stories.
Each story = one PR. Write scope descriptions, not implementation plans.
Scout reports are attached — use them to ground file estimates."

### 5.4 Spec Review Gate

The driver presents story sketches to the user. Approve/edit/remove controls.
The driver blocks until the user explicitly approves. This is the one
mandatory human gate.

### 5.5 Pre-Execution Analysis (Orchestrator)

**Input**: `epic.md` with approved stories, `decisions.md`.
**Output**: Updated `epic.md` with sequencing, per-story `status.md` files.
**Step sequence**: Pre-execution.
**Tools**: `koan_select_story`, `koan_complete_step`, `write`.

The orchestrator analyzes approved stories to determine dependency order and
calls `koan_select_story` to pick the first story. For the initial
implementation, execution is sequential. The tool writes `selected` to both
`state.json` (for the driver) and `status.md` (for future LLM reads). The
driver reads `state.json` after the orchestrator exits and spawns the planner
for the selected story.

### 5.6 Detail-Plan (Per-Story, JIT)

**Input**: `story.md`, `decisions.md`, the _current_ codebase (via scouts).
**Output**: `plan/plan.md`, `plan/context.md`, `plan/verify.md`.

The driver fans out scouts in parallel via `pool()` to read the actual current
file contents (which may have changed from earlier stories). Each scout writes
its findings to `stories/{story-id}/scouts/{scout-id}.md`. The driver then
spawns the planner with the story sketch, `decisions.md`, and scout output
file paths. The planner synthesizes scout findings and produces three
artifacts:

`plan.md` — file-by-file implementation steps with rationale. Describes
behavior changes in prose, not code diffs. References `decisions.md` for
design rationale.

`context.md` — curated code snippets the executor needs. The need-to-know
principle: the planner pre-selects what's relevant so the executor doesn't
re-explore the codebase.

`verify.md` — concrete, executable checks ordered from cheapest (grep, build)
to most expensive (test suite, LLM review). References the testing strategy
from `decisions.md`.

The planner flags high-risk steps and appends any new decisions to
`decisions.md`. The planner must NOT write code, execute changes, make
user-facing decisions without recording them, or plan beyond the current
story's scope.

**Prompt gist**: "Write a step-by-step implementation plan: which file, which
function, what change, why. Include enough detail that a coding agent can
execute without re-deriving reasoning. Produce plan.md, context.md, verify.md."

### 5.7 Execute (Per-Story)

**Input**: `plan.md`, `context.md`.
**Output**: Code changes to the codebase.
**Permission**: WRITE_TOOLS (edit, write) — new tier.

The executor implements each step in the plan, in order. It does not explore
the codebase beyond `context.md`. If it encounters a plan-reality mismatch (a
file doesn't look like the plan expected, a function was renamed, a dependency
is missing), it uses `koan_ask_question` to escalate to the user or stops and
reports the discrepancy for the orchestrator to handle.

The executor inherits core patterns from the current developer prompt: scope
violation checks, context drift tolerance, escalation patterns, directive
marker handling, comment hygiene. Key differences: scope is one story (not an
entire plan), context is pre-curated, escalation goes to the orchestrator.

**Prompt gist**: "Implement each step in order. If the code doesn't match the
plan's expectations — STOP and report. Do not improvise. Do not add features
not in the plan. Do not refactor code the plan doesn't mention."

### 5.8 Post-Execution Assessment (Orchestrator)

**Input**: `verify.md`, `plan.md`, `status.md`, git diff, `epic.md`.
**Output**: Updated `status.md` (via tools), potentially updated `story.md`
files, next-story selection.
**Step sequence**: Post-execution.
**Tools**: `koan_complete_story`, `koan_retry_story`, `koan_escalate`,
`koan_select_story`, `koan_skip_story`, `koan_complete_step`, `write`.

The orchestrator runs four steps:

1. **Verify**: Run `verify.md` checks (automated via bash, LLM review for
   high-risk stories). Record findings.
2. **Verdict**: Based on verification results, call exactly one of:
   - `koan_complete_story(story_id)` → story status becomes `done`.
   - `koan_retry_story(story_id, failure_summary)` → story status becomes
     `retry`. The driver enforces the retry budget; if exhausted, the driver
     sets status to `escalated` and presents to the user.
   - `koan_escalate(story_id, problem, candidates, recommended)` → story
     status becomes `escalated`. The driver presents the escalation to the
     user via the ask UI.
3. **Propagate** (only if story completed): Review remaining story sketches
   against what was learned during execution. Use `write` to update
   `story.md` files and append to `decisions.md` with `[autonomous]` marker.
   May call `koan_skip_story` for stories no longer needed.
4. **Select next** (only if story completed and more stories remain): Call
   `koan_select_story(next_story_id)`. If no stories remain, don't call —
   the driver infers epic completion from state (all stories `done` or
   `skipped`).

After the orchestrator exits, the driver reads state files and applies
deterministic routing rules (see §2.8).

### 5.9 Widget (Full Redesign)

The current 3-phase fixed timeline is replaced. The new widget shows:
epic-level progress, current story status and phase, active subagent with step
progress, log stream, and count of autonomous adjustments since last human
interaction. Ground-up redesign of layout and content, reusing rendering
building blocks.

---

## 6. Implementation Sequence

Hard cutover: replace the old system entirely. There is no parallel running of
old and new code — `driver.ts` replaces `session.ts` at the entry point level,
and `koan.ts` is rewired to the new driver from step 1.

**Step 1**: Driver shell and state directory. Create `driver.ts` (replaces
`session.ts`). Epic directory creation, `koan_plan` entry point wiring.

**Step 2**: Permission model and infrastructure types. Rewrite
`PHASE_PERMISSIONS` → `ROLE_PERMISSIONS` (§8.2). Rewrite model resolution
from 5×4 matrix to role → tier → model (§8.6). New CLI flags (§8.4). New
spawn functions (§8.3). Register orchestrator tools (`koan_select_story`,
`koan_complete_story`, `koan_retry_story`, `koan_escalate`, `koan_skip_story`)
per §2.7.

**Step 3**: Intake phase. Multi-step phase class. Read `conversation.jsonl`,
write `context.md`, identify gaps, present questions via IPC, write
`decisions.md`.

**Step 4**: Epic decomposition. Decomposer phase class + scout phase class.
Scouts in parallel via `pool()`. Decomposer produces `epic.md` + per-story
`story.md`.

**Step 5**: Spec review gate. Story sketch presentation via widget.
Approve/edit/remove controls. Block until confirmed.

**Step 6**: Orchestrator. Phase class with two step sequences (pre-execution,
post-execution). Uses `koan_select_story`, `koan_complete_story`,
`koan_retry_story`, `koan_escalate`, `koan_skip_story` (§2.7). State
communicated via `state.json` files (JSON for driver) and `status.md`
files (markdown for LLMs); driver reads `state.json` and applies
deterministic routing rules (§2.8).

**Step 7**: Detail-plan phase. Planner phase class + scouts for current
codebase. Produces `plan.md` + `context.md` + `verify.md`.

**Step 8**: Execute phase. Executor phase class. Full write access. One story
at a time, pre-curated context.

**Step 9**: Driver execution loop. Wire steps 6–8 into the per-story cycle.
Handle retry budget, escalation via IPC, epic completion.

**Step 10**: Widget redesign. Ground-up layout and content redesign, reusing
rendering building blocks.

---

## 7. What This Does Not Cover

This plan deliberately excludes topics that need separate design:

- **Parallel story execution**: Sequential initially. Parallel adds git
  worktree isolation and merge conflict handling. Deferred.

- **Mid-execution monitoring**: The initial implementation spawns the executor
  and waits. Active observation and real-time steering are deferred.

- **Plan recovery from midpoint**: Partial story success currently means full
  retry or escalation. A future refinement could produce continuation plans
  from the failure point. Requires the executor to report where it failed and
  what completed. Deferred.

- **Multi-plan selection**: One plan per story. A future refinement could
  generate alternatives for high-risk stories, or distinguish execution
  failures (retry same plan) from approach failures (different plan needed).
  Deferred.

- **Complexity-adaptive workflow**: Full pipeline for every request initially.
  A future refinement adds a fast path: if intake produces zero questions and
  decomposition produces one story, skip the spec review gate. Deferred.

- **Resumption after interruption**: If the user aborts mid-epic (kills the
  process), the file-on-disk structure preserves all state. Driver resumption
  logic to pick up from where it left off needs design. Note that mid-execution
  _questions_ (ambiguity, clarification) do not require resumption —
  `koan_ask_question` handles those in-place without interrupting the session.

- **Cost instrumentation**: Per-phase and per-subagent token counting. Should
  be day-one but reporting format needs design.

- **Model routing configuration**: Per-phase model selection UX needs design.
  Infrastructure exists.

---

## 8. Infrastructure Type Updates

The current infrastructure types encode the old role and phase names. These
must be rewritten for the new architecture. The following specifies the
replacement types.

### 8.1 Role and phase types

Replace the current `PhaseRow` / `SubPhase` / `PhaseModelKey` system
(`model-phase.ts`) with role-based types:

```typescript
// Subagent roles — the six LLM roles plus the two carried-over utility roles.
type SubagentRole =
  | "intake"
  | "scout"
  | "decomposer"
  | "orchestrator"
  | "planner"
  | "executor";

// Model tiers — maps to the three tiers in §1.
type ModelTier = "strong" | "standard" | "cheap";

// Role → tier mapping (from §2.5).
const ROLE_MODEL_TIER: Record<SubagentRole, ModelTier> = {
  intake: "strong",
  scout: "cheap",
  decomposer: "strong",
  orchestrator: "strong",
  planner: "strong",
  executor: "standard",
};
```

### 8.2 Permission map

Replace the current `PHASE_PERMISSIONS` map (`permissions.ts`) with
role-based permissions. The key change is the new WRITE_TOOLS tier
for the executor and epic-directory-scoped writes for planning roles.

```typescript
// Tools available to the orchestrator (see §2.7).
const ORCHESTRATOR_TOOLS = new Set([
  "koan_complete_step",
  "koan_ask_question",
  "koan_select_story",
  "koan_complete_story",
  "koan_retry_story",
  "koan_escalate",
  "koan_skip_story",
]);

// Tools available to all planning subagents (intake, decomposer, planner).
// These roles can write to the epic directory but NOT the codebase.
const PLANNING_TOOLS = new Set([
  "koan_complete_step",
  "koan_ask_question",
  // Write tool scoped to epic directory (enforced at tool_call handler level).
]);

// Tools available to scouts.
const SCOUT_TOOLS = new Set([
  "koan_complete_step",
  // READ_TOOLS only (always allowed). No write access.
]);

// Tools available to the executor.
// Full WRITE_TOOLS access to the codebase.
const EXECUTOR_TOOLS = new Set([
  "koan_complete_step",
  "koan_ask_question",
  // WRITE_TOOLS (edit, write) — codebase access.
]);

const ROLE_PERMISSIONS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["intake", PLANNING_TOOLS],
  ["scout", SCOUT_TOOLS],
  ["decomposer", PLANNING_TOOLS],
  ["orchestrator", ORCHESTRATOR_TOOLS],
  ["planner", PLANNING_TOOLS],
  ["executor", EXECUTOR_TOOLS],
]);
```

### 8.3 Spawn functions

Replace the current role-specific spawn functions (`subagent.ts`) with
new functions for the six roles. The core `spawnSubagent()` function and
its process lifecycle management are preserved. New spawn functions:

- `spawnIntake(opts)` — strong model, interactive (IPC polling required).
- `spawnScout(opts)` — cheap model, narrow question + output file path.
- `spawnDecomposer(opts)` — strong model, reads intake output + scout files.
- `spawnOrchestrator(opts)` — strong model, two step sequences (pre/post).
- `spawnPlanner(opts)` — strong model, reads story sketch + scout files.
- `spawnExecutor(opts)` — standard model, WRITE_TOOLS access.

### 8.4 CLI flags

Replace the current `--koan-role` flag values with the new role names.
The `--koan-phase` flag is replaced by step-sequence identifiers where
a role has multiple sequences (e.g., orchestrator pre-execution vs
post-execution). The `--koan-fix` and `--koan-qr-item` flags are removed
(no QR system).

New flags:

- `--koan-role`: `intake | scout | decomposer | orchestrator | planner | executor`
- `--koan-step-sequence`: `pre-execution | post-execution` (orchestrator only)
- `--koan-epic-dir`: Path to the epic directory (replaces `--koan-plan-dir`)
- `--koan-story-id`: Current story ID (for per-story subagents)
- `--koan-subagent-dir`: Subagent working directory (preserved)

### 8.5 Audit event shapes

The `KOAN_SHAPES` record in `audit.ts` must be updated to remove all 44
plan mutation tool shapes and add shapes for the new orchestrator tools
(`koan_select_story`, `koan_complete_story`, `koan_retry_story`,
`koan_escalate`, `koan_skip_story`).

### 8.6 Model resolution

The current 5×4 matrix (`model-phase.ts`, `model-config.ts`,
`model-resolver.ts`) is replaced by a simple role → tier → model lookup:

1. Look up the role's tier from `ROLE_MODEL_TIER`.
2. Look up the model for that tier from `~/.koan/config.json`.
3. If no config, return `undefined` (fall back to pi's active model).

Config schema:

```json
{
  "modelTiers": {
    "strong": "anthropic/claude-sonnet-4",
    "standard": "anthropic/claude-sonnet-4",
    "cheap": "anthropic/claude-haiku-4"
  }
}
```

---

## 9. Post-Implementation Notes

This section records decisions made during implementation, deviations from
the plan, resolved ambiguities, and remaining work. Added after the initial
big-bang rewrite was completed.

### 9.1 Resolved ambiguities

**`status.md` and driver state management.** The plan left the `status.md`
schema unspecified and implied the driver would parse it. Resolution: the
driver never parses `status.md` or any markdown file. The orchestrator reads
`status.md` for context, then communicates decisions to the driver by calling
tools (`koan_select_story`, `koan_complete_story`, etc.). Each tool writes
both:

- A JSON `state.json` file under `stories/{story-id}/` — for driver
  consumption. Machine-readable, deterministic format.
- A markdown `status.md` file in the same directory — for LLM consumption in
  future orchestrator invocations. Human-readable summary of the state.

This establishes a clean invariant: **`.json` and `.jsonl` files are for
driver consumption only; `.md` files are for LLM consumption.** Tools bridge
the two worlds.

**Scout write access.** §8.2 listed `SCOUT_TOOLS` with no write access, but
§5.3 described scouts writing findings to markdown files. Resolution: scouts
are granted `write`/`edit` scoped to the epic directory (same as other
planning roles). They need to write their output file.

**Orchestrator verification and `bash`.** §5.8 described the orchestrator
running `verify.md` checks via bash, but §8.2's `ORCHESTRATOR_TOOLS` didn't
explicitly include bash. Resolution: bash is in `READ_TOOLS` (always allowed),
and the orchestrator also gets explicit bash access in `ROLE_PERMISSIONS`.
The permission system does not distinguish "read bash" from "write bash" —
this is an accepted limitation consistent with the current design.

**Orchestrator step sequence dispatch.** The plan described two step sequences
but didn't specify the dispatch mechanism. Resolution: a single
`OrchestratorPhase` class reads `config.stepSequence` in `begin()` and
configures its total steps (2 for pre-execution, 4 for post-execution) and
step name/guidance functions accordingly. The `--koan-step-sequence` CLI flag
carries the sequence identifier.

### 9.2 Implementation decisions

**`PlanRef.dir` reuse.** The existing `PlanRef` interface in `lib/dispatch.ts`
has a `dir` field and a `qrPhase` field. Rather than modifying the dispatch
infrastructure, `PlanRef.dir` now points to the epic directory. The `qrPhase`
field is unused but retained to avoid touching the kept `dispatch.ts` file.

**Model resolution at spawn time.** Each spawn function
(`spawnIntake`, `spawnScout`, etc.) calls `resolveModelForRole(role)` to look
up the configured model for the role's tier. If no config exists, `--model`
is omitted and pi uses its active model. This is consistent with the old
system's spawn-time resolution pattern.

**Orchestrator tools validate transitions.** `koan_select_story` validates
that the story's current status is `"pending"` or `"retry"` before
transitioning to `"selected"`. This allows the orchestrator to re-select
retried stories. Other tools do not enforce preconditions at the tool
level — the orchestrator is trusted to call tools at appropriate points,
and the driver applies its own state checks after the orchestrator exits.

**Epic directory structure.** Implemented as specified in §2.3, under
`~/.koan/state/epics/{epic-id}/`. The `createEpicDirectory` function in
`epic/state.ts` generates the ID using the same timestamp+slug pattern as the
old `createPlanInfo`, creates subdirectories (`stories/`, `scouts/`,
`subagents/`), and writes an initial `epic-state.json`.

**Background context.** The old system loaded background context from
`plan.json`. The rewritten `formatStepWithBackgroundContext` reads
`context.md` from the epic directory (the intake output). If `context.md`
doesn't exist yet (e.g., during the intake phase itself), it falls back to
an empty context string.

**Agent prompts.** `lib/agent-prompts.ts` still contains the old role prompts
(architect, developer, quality-reviewer, technical-writer). These are not
used by the new system — each phase class has its own `prompts.ts` with
role-specific system prompts and step guidance. The old prompts file is
retained but dormant.

### 9.3 Deviations from the plan

**Architecture is faithful; behavioral wiring had defects.** The
implementation follows the plan's two-phase architecture (epic creation →
story execution loop), role definitions, tool inventory, permission model,
and model tier system faithfully. However, post-implementation analysis
(§9.6) found runtime wiring defects in phase prompt injection, prompt path
references, and story state initialization that would prevent end-to-end
execution. These are corrected in §9.6.

**`handleFinalize()` dropped.** §3 originally described a `handleFinalize()`
method on phase classes. Implementation uses the orchestrator's
post-execution verification instead — phase classes simply advance steps
and terminate. Output validation is the orchestrator's responsibility, not
something each phase class does for itself. §3 has been updated.

**`koan_ask_question` excluded from scout.** §3 originally stated all
subagent roles get `koan_ask_question`. Implementation excludes scout —
scouts are narrow-scope codebase investigators that answer one question
and write one file. They should not need user interaction. §3 has been
updated.

**`koan_select_story` accepts `retry` status.** §2.7 originally specified
`pending → selected` only. The orchestrator's post-execution step 4 needs
to re-select retried stories, so the tool now accepts both `pending` and
`retry`. §2.7 has been updated.

**Driver reads `state.json`, not `status.md`.** §2.8 originally said the
driver reads `status.md`. The implementation reads `state.json` exclusively
(the invariant from §9.1: JSON for driver, markdown for LLMs). §2.8 has
been updated.

**EpicState reload on each phase transition.** The driver reloads
`epic-state.json` before each save to avoid overwriting the `stories` list
that the decomposer may have populated. The plan didn't specify this, but
it's a correctness requirement — a single-snapshot-then-spread pattern would
silently lose story data.

**Config migration.** The plan didn't specify migration from the old
`phaseModels` config key. Implementation: the old key is silently ignored.
No migration, no warning. Users with old config get the default behavior
(no model overrides, pi's active model used for all roles).

### 9.4 Remaining work

Items marked TODO in the codebase. These are deferred capabilities, not
missing implementation of specified features.

**Scout question generation.** The driver stubs
`runDecompositionScouts()` and `runStoryScouts()` — they return empty
arrays. The plan describes scouts answering "narrow codebase questions,"
but the mechanism for generating those questions is underspecified. Two
options:

1. The intake phase writes a `scout-questions.json` manifest alongside
   `context.md`, listing questions for the decomposition scouts. The planner
   does the same for per-story scouts. The driver reads these manifests.
2. A dedicated "question generation" step in the driver constructs
   questions from the structured output of intake/planning phases.

Option 1 is simpler and consistent with the "tools write JSON for the
driver" pattern. It requires adding a new artifact to the intake and
planner phase outputs.

**Spec review gate UI.** The driver auto-approves after the decomposer
exits. The plan specifies a widget with approve/edit/remove controls per
story. This requires a new TUI component and the driver blocking until
user confirmation. Deferred to the widget redesign (§6 step 10).

**Escalation presentation.** When a story reaches `escalated` status, the
driver currently returns a failure summary instead of presenting the
escalation to the user interactively. The plan specifies presenting the
problem, candidate solutions, and recommended solution via the ask UI.
This requires integrating the IPC ask flow into the driver's execution
loop — the infrastructure exists (`koan_ask_question`, `pollWithIpcDetection`)
but the driver doesn't yet use it.

**Widget redesign.** The old `WidgetController` is retained but doesn't
reflect the new epic/story lifecycle. The plan calls for a ground-up
redesign (§5.9) showing epic progress, current story, active subagent,
step info, log stream, and autonomous adjustment count. Deferred.

**Cost instrumentation.** §7 mentions per-phase and per-subagent token
counting as "should be day-one." Not implemented. The EventLog captures
tool calls but not token usage.

**Resumption after interruption.** §7 defers this. The file-on-disk
structure preserves state, but the driver has no resume path. If the
process dies mid-story, the driver must be restarted from scratch. Adding
resume requires the driver to detect existing state on startup and
reconstruct its position in the execution loop.

### 9.5 File inventory

New and rewritten files (43 source files, ~6,500 lines total):

```
extensions/koan.ts                          # REWRITTEN: new flags, driver integration
src/planner/types.ts                        # NEW: SubagentRole, ModelTier, StoryStatus, ROLE_MODEL_TIER
src/planner/driver.ts                       # NEW: epic pipeline coordinator
src/planner/subagent.ts                     # REWRITTEN: 6 role-specific spawn functions
src/planner/model-phase.ts                  # REWRITTEN: re-exports from types.ts + ALL_MODEL_TIERS, isModelTier
src/planner/model-config.ts                 # REWRITTEN: 3-tier config I/O
src/planner/model-resolver.ts               # REWRITTEN: role → tier → model
src/planner/epic/types.ts                   # NEW: EpicState, StoryState
src/planner/epic/state.ts                   # NEW: state I/O, directory management
src/planner/phases/dispatch.ts              # REWRITTEN: 6-role routing
src/planner/phases/intake/{phase,prompts}.ts      # NEW
src/planner/phases/scout/{phase,prompts}.ts       # NEW
src/planner/phases/decomposer/{phase,prompts}.ts  # NEW
src/planner/phases/orchestrator/{phase,prompts}.ts # NEW
src/planner/phases/planner/{phase,prompts}.ts     # NEW
src/planner/phases/executor/{phase,prompts}.ts    # NEW
src/planner/tools/orchestrator.ts           # NEW: 5 state-transition tools
src/planner/tools/index.ts                  # REWRITTEN: 3 tool groups
src/planner/lib/permissions.ts              # REWRITTEN: role-based + path scoping
src/planner/lib/audit.ts                    # MODIFIED: new KOAN_SHAPES
src/planner/ui/config/model-selection.ts    # REWRITTEN: 3-tier editor
src/planner/ui/config/menu.ts              # MODIFIED: new imports
src/utils/plan.ts                          # MODIFIED: ID helpers only
```

Deleted files (~10,200 lines removed):

```
# Old architecture (replaced by driver + phases + epic state)
src/planner/session.ts
src/planner/state.ts
src/planner/plan/{types,serialize,render,validate}.ts
src/planner/plan/mutate/{index,top-level,decisions,milestones,code,structure,background-context}.ts
src/planner/qr/{types,mutate,severity}.ts
src/planner/phases/plan-design/{phase,prompts,fix-phase,fix-prompts}.ts
src/planner/phases/plan-code/{phase,prompts,fix-phase,fix-prompts}.ts
src/planner/phases/plan-docs/{phase,prompts,fix-phase,fix-prompts}.ts
src/planner/phases/qr-decompose/{phase,prompts}.ts
src/planner/phases/qr-verify/{phase,prompts}.ts
src/planner/tools/{getters,setters,entity-design,entity-code,entity-structure,entity-context,qr}.ts
tests/{model-config,model-phase,model-resolver,session-model-threading,subagent-model,qr-grouped-verify,widget,background-context}.test.ts

# Dead code removed during post-analysis cleanup (§9.6)
src/planner/lib/background-context-prompt.ts  # rewritten but never imported
src/planner/lib/conversation-trigger.ts       # referenced old phase IDs
src/planner/lib/resources.ts                  # old resource resolver
src/planner/lib/agent-prompts.ts              # old role prompts (dormant)
src/utils/lock.ts                             # unused
src/utils/progress.ts                         # unused
tests/progress.test.ts                        # tested unused module
```

### 9.6 Post-analysis corrections

Post-implementation analysis found runtime wiring defects that would prevent
end-to-end execution. This section documents each defect, why it happened,
and the correction. Changes to earlier plan sections (§2.7, §2.8, §3) are
cross-referenced.

**Step 1 prompt injection replaces instead of appending.** All 6 phase
classes' `context` event handlers replaced the entire user message with
the step 1 prompt. This discarded the spawn prompt, which carries
role-specific context (the scout's question, the decomposer's scout file
list, the executor's retry context). Correction: the `context` handler
now appends the step guidance to the existing user message instead of
replacing it. If the original message is present, the step guidance is
added after a separator. This preserves any context the spawn function
embedded in the prompt while adding the structured step instructions.

Affects: all 6 `phases/*/phase.ts` files.

**Retry context not reaching `ExecutorPhase`.** `dispatch.ts` constructed
`ExecutorPhase` without reading `retryContext` from a flag, so retried
executor invocations received no failure context. Correction: added
`--koan-retry-context` flag; `dispatch.ts` reads it and passes it into
the `ExecutorPhase` config. The executor's step 1 guidance includes the
retry context when present.

Affects: `extensions/koan.ts` (flag registration), `phases/dispatch.ts`
(flag reading), `subagent.ts` (flag passing in `spawnExecutor`).

**Prompt paths missing `stories/` prefix.** Planner, executor, and
orchestrator prompts referenced `${storyId}/plan/plan.md` etc., but the
actual artifact structure is `stories/${storyId}/...` (per §2.3 and
`epic/state.ts`). Correction: all prompt paths now include the `stories/`
prefix.

Affects: `phases/planner/prompts.ts`, `phases/executor/prompts.ts`,
`phases/orchestrator/prompts.ts`.

**Orchestrator post-exec step 2 prompt told LLM not to call
`koan_complete_step`.** The prompt said "the verdict tool signals step
completion", but verdict tools (`koan_complete_story`, etc.) do not
trigger `dispatch.onCompleteStep` — only `koan_complete_step` does. The
correct flow is: call the verdict tool, then call `koan_complete_step` to
advance. Correction: removed the incorrect instruction from the
orchestrator prompt. The verdict tools and step completion are independent
actions.

Affects: `phases/orchestrator/prompts.ts` only (infrastructure is correct).

**`koan_select_story` rejected `retry` status.** The tool enforced
`status === "pending"` only, but the orchestrator's post-execution step 4
needs to re-select retried stories. Correction: tool now accepts both
`"pending"` and `"retry"`. §2.7 state transition table updated.

Affects: `tools/orchestrator.ts`, §2.7.

**Story state initialization gap.** The driver never called
`ensureStoryDirectory()`, relying on the decomposer LLM to create valid
`state.json` files. But the decomposer writes markdown story sketches —
it has no reason to know the JSON state format. Correction: the driver
calls `ensureStoryDirectory()` for each story ID listed in
`epic-state.json` after the decomposer exits, before entering the story
execution loop. `ensureStoryDirectory()` creates the directory structure
and writes an initial `state.json` with `"pending"` status if one doesn't
already exist.

Affects: `driver.ts` (story initialization step after decomposer).

Note: the decomposer must register story IDs in `epic-state.json` (via
the `stories` array) for the driver to discover them. This is part of
the decomposer's contract — it writes `epic.md` (markdown, for LLMs)
and updates `epic-state.json` (JSON, for the driver) with the story list.
The decomposer tools or write-tool instructions must include this.

**Duplicate `ModelTier` / `ROLE_MODEL_TIER` definitions.** Both `types.ts`
and `model-phase.ts` defined identical copies. Different consumers imported
from different files. Correction: canonical definitions live in `types.ts`.
`model-phase.ts` re-exports from `types.ts` and adds only the
`ALL_MODEL_TIERS` array and `isModelTier()` guard that are specific to
model configuration. No duplicate definitions remain.

Affects: `types.ts` (canonical source), `model-phase.ts` (re-export +
utilities), all consumers unchanged (imports still resolve).

**Dead code removed.** Six unreferenced files were removed:
`lib/background-context-prompt.ts` (rewritten during implementation but
never imported — its functionality was superseded by per-phase prompt
construction), `lib/conversation-trigger.ts` (referenced old phase IDs),
`lib/resources.ts` (old resource path resolver), `lib/agent-prompts.ts`
(old role prompts for deleted roles), `utils/lock.ts` (unused utility),
`utils/progress.ts` + `tests/progress.test.ts` (progress tracking utility
that was never imported by the new system).

Affects: §9.5 file inventory updated.

### 9.7 Plan sections amended by post-analysis

For traceability, the following earlier plan sections were modified during
the §9.6 corrections:

| Section   | Change                                                            | Reason                                                             |
| --------- | ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| §2.1      | Epic completion reads `state.json` not `status.md`                | Aligns with §9.1 invariant                                         |
| §2.6      | Story state machine: driver writes `state.json`, tools write both | Clarifies dual-format write pattern                                |
| §2.7      | `koan_select_story` transition: `pending` → `pending or retry`    | Orchestrator needs to re-select retried stories                    |
| §2.8      | Driver reads `state.json` not `status.md`                         | Aligns with §9.1 invariant (JSON for driver, markdown for LLMs)    |
| §3        | `handleFinalize()` removed from lifecycle description             | Not implemented; verification is orchestrator's job                |
| §3        | `koan_ask_question` scoped to all roles except scout              | Scout is a narrow investigator, doesn't need user interaction      |
| §5.5      | `koan_select_story` writes to both `state.json` and `status.md`   | Clarifies dual-format write                                        |
| §6 step 6 | State communicated via `state.json` + `status.md`                 | Was `status.md` only                                               |
| §9.2      | `koan_select_story` accepts `pending` or `retry`                  | Matches §2.7 update                                                |
| §9.3      | Acknowledges behavioral deviations, not just architecture         | §9.6 defects are real deviations from the plan's behavioral intent |
| §9.4      | Removed `agent-prompts.ts` cleanup item                           | File deleted as dead code in §9.6                                  |
| §9.5      | Updated file inventory                                            | Reflects dead code removal and types.ts consolidation              |

### 9.8 §9.6 corrections implemented

All 8 corrections described in §9.6 have been implemented and verified.
This section records the implementation details.

**Step 1 prompt append (all 6 phase classes).** The `context` event
handler in each phase class's `registerHandlers()` was changed from
replacing the user message to appending step guidance after it. The
pattern:

```typescript
this.pi.on("context", (event) => {
  if (!this.active || this.step !== 1 || !this.step1Prompt) return undefined;
  const messages = event.messages.map((m) => {
    if (m.role !== "user") return m;
    const existing = typeof m.content === "string" ? m.content.trim() : "";
    const combined =
      existing.length > 0
        ? `${existing}\n\n---\n\n${this.step1Prompt!}`
        : this.step1Prompt!;
    return { ...m, content: combined };
  });
  return { messages };
});
```

This preserves the spawn prompt (scout question, decomposer scout file
list, executor retry context, etc.) while adding the structured step
instructions after a `---` separator. If the spawn prompt is empty the
step guidance is used alone.

**Retry context flag.** Three files changed:

- `extensions/koan.ts`: registered `koan-retry-context` flag (string,
  default `""`)
- `src/planner/subagent.ts`: `spawnExecutor` pushes
  `--koan-retry-context` to `extraFlags` when `opts.retryContext` is set
- `src/planner/phases/dispatch.ts`: executor case reads
  `pi.getFlag("koan-retry-context")` and passes it to `ExecutorPhase`
  config as `retryContext`

The retry context now reaches the executor phase through two independent
channels: (1) in the spawn prompt text (preserved by the append fix
above) and (2) in the phase config via the CLI flag (consumed by
`executorStepGuidance` to inject failure context into step 1 guidance).
Channel 2 is the structured path; channel 1 is a backup that ensures
the LLM sees the context even if the phase machinery fails.

**Prompt path prefix.** All `${storyId}/...` references in prompt
templates changed to `stories/${storyId}/...`:

- `planner/prompts.ts`: 4 occurrences (story.md, plan/plan.md,
  plan/context.md, plan/verify.md)
- `executor/prompts.ts`: 2 occurrences (plan/plan.md, plan/context.md)
- `orchestrator/prompts.ts`: 1 occurrence (plan/verify.md, plus its
  fallback template string)

Paths now match the actual directory structure in `epic/state.ts`.

**Orchestrator step 2 prompt.** The instruction "Do NOT call
`koan_complete_step` — the verdict tool signals step completion" was
replaced with "Then call `koan_complete_step` after the verdict tool to
advance to the next step." The verdict tools and step completion are
independent actions — the LLM calls the verdict tool first, then
`koan_complete_step` to advance the phase.

**`koan_select_story` retry acceptance.** In `tools/orchestrator.ts`:

- Guard: `state.status !== "pending"` → `state.status !== "pending" &&
state.status !== "retry"`
- Error message: includes both accepted statuses
- Tool description: updated to mention both `pending` and `retry`

**Story state initialization.** In `driver.ts`, after the decomposer
succeeds and before the spec review gate, the driver now iterates over
`epicState.stories` and calls `ensureStoryDirectory()` for each. This
creates the directory structure (`stories/{id}/`, `stories/{id}/scouts/`,
`stories/{id}/plan/`) and writes an initial `state.json` with `"pending"`
status if one doesn't already exist. The `ensureStoryDirectory` import
was added to the existing import block from `./epic/state.js`.

Contract note: the decomposer must register story IDs in
`epic-state.json` (the `stories` array) for the driver to discover
them. This is how the decomposer communicates the story list to the
driver — via JSON, consistent with the §9.1 invariant. The decomposer's
`write` tool output must include an `epic-state.json` update. This
contract should be enforced in the decomposer's step 2 prompt (the
prompt currently instructs writing `epic.md` and per-story `story.md`
files but does not explicitly mention updating `epic-state.json`).

**`ModelTier` deduplication.** `model-phase.ts` no longer defines
`ModelTier`, `SubagentRole`, or `ROLE_MODEL_TIER` locally. Instead:

- `export type { ModelTier, SubagentRole } from "./types.js"`
- `export { ROLE_MODEL_TIER } from "./types.js"`
- Local definitions retained only for `ALL_MODEL_TIERS` (array) and
  `isModelTier()` (type guard), which are model-config concerns not
  needed in the core `types.ts`

All four consumers (`model-selection.ts`, `menu.ts`, `model-resolver.ts`,
`model-config.ts`) continue to import from `model-phase.js` without
changes — the re-exports preserve the public API.

**Dead code removal.** Seven files removed:

- `src/planner/lib/background-context-prompt.ts` (untracked, `rm`)
- `src/planner/lib/conversation-trigger.ts` (`git rm`)
- `src/planner/lib/resources.ts` (`git rm`)
- `src/planner/lib/agent-prompts.ts` (`git rm`)
- `src/utils/lock.ts` (`git rm`)
- `src/utils/progress.ts` (`git rm`)
- `tests/progress.test.ts` (`git rm`)

Post-removal import scan confirms zero dangling references.

**Verification.** After all corrections: `npx tsc --noEmit` produces
zero errors; `npm test` runs 21 tests with 21 passes and 0 failures;
43 source files remain.

---

## 10. Post-Analysis: Architectural Corrections and Remaining Work

Post-implementation codebase analysis (2026-03-11) identified architectural
violations, missing runtime wiring, and underspecified components. This
section records the corrections and remaining work items for the next
rewrite pass. All items here take precedence over earlier sections where
they conflict.

### 10.1 Core invariant: LLM/driver communication boundary

The following invariant is the single most important architectural rule in
koan. It is documented in `AGENTS.md` at the repository root.

> LLMs write **markdown files only**. LLMs communicate with the driver
> through **tool calls only**. The driver maintains `.json` state files
> internally — no LLM ever reads or writes a `.json` file.

Example: orchestrator calls `koan_complete_story(story_id)` → tool code
writes `state.json` + `status.md` → driver reads `state.json` to route
next action. The orchestrator never touches `state.json` directly.

This invariant was already implicit in §9.1 but was violated in practice:
§9.6 and §9.8 describe the decomposer updating `epic-state.json` directly.
§10.2 corrects this.

### 10.2 Story discovery: filesystem scan, not LLM-written JSON

**Problem.** §9.6 and §9.8 state that the decomposer must register story
IDs in `epic-state.json` (the `stories` array) for the driver to discover
them. This requires the decomposer LLM to write a JSON file, violating
§10.1.

**Correction.** The driver discovers stories by scanning the filesystem
after the decomposer exits. The decomposer writes `stories/{id}/story.md`
files (markdown, per §10.1). The driver scans `stories/*/story.md` and
populates `epic-state.json.stories` itself.

Implementation:

```typescript
// In driver.ts, after decomposer exits:
import { readdir } from "node:fs/promises";
import { join } from "node:path";

async function discoverStoryIds(epicDir: string): Promise<string[]> {
  const storiesDir = join(epicDir, "stories");
  const entries = await readdir(storiesDir, { withFileTypes: true });
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort(); // deterministic order
}
```

After scanning, the driver calls `ensureStoryDirectory()` for each
discovered ID (creating `state.json` with `"pending"` status) and writes
the ID list to `epic-state.json`. This replaces the contract note in §9.8.

**Affected sections:** §5.3 (decomposer output no longer includes JSON),
§9.6 (story state initialization correction superseded), §9.8 (contract
note superseded).

### 10.3 Dispatch simplification: prompt-only phase config

**Problem.** `dispatch.ts` constructs phase classes with config fields
(`scoutFiles`, `question`, `outputFile`) that are always empty. The real
context is in the spawn prompt (initial user message). The phase class
API is misleading — it accepts structured config that it never uses
functionally.

**Correction.** Phase class constructors accept only routing-level config
that the driver needs for structural decisions:

- All phases: `epicDir` (for permission scoping)
- Orchestrator: `stepSequence` (determines step count and guidance)
- Executor: `retryContext` (injected into step 1 guidance via CLI flag)
- Story-scoped phases (planner, executor, orchestrator post-exec): `storyId`

All role-specific context (scout focus area, decomposer scout file list,
planner story details) is embedded in the spawn prompt by the spawn
function. The phase class appends step guidance to this prompt via the
`context` event handler (the §9.8 append pattern).

Fields to remove from phase constructors:

- `ScoutPhase`: remove `question`, `outputFile`
- `DecomposerPhase`: remove `scoutFiles`
- `PlannerPhase`: remove `scoutFiles`

The `dispatch.ts` cases for these phases simplify to:

```typescript
case "scout": {
  const phase = new ScoutPhase(pi, { epicDir: config.epicDir }, dispatch, planRef, logger, eventLog);
  await phase.begin();
  break;
}
case "decomposer": {
  const phase = new DecomposerPhase(pi, { epicDir: config.epicDir }, dispatch, planRef, logger, eventLog);
  await phase.begin();
  break;
}
case "planner": {
  const phase = new PlannerPhase(pi, { epicDir: config.epicDir, storyId: config.storyId ?? "" }, dispatch, planRef, logger, eventLog);
  await phase.begin();
  break;
}
```

### 10.4 Parent-side IPC responder

**Problem.** `koan_ask_question` (subagent side) writes an IPC request file
and polls for a response. No parent-side code reads the request, renders the
ask UI, or writes a response. Intake — the first phase in the pipeline —
uses `koan_ask_question` to ask the user clarifying questions. Without the
parent responder, intake hangs indefinitely on its first question.

**Correction.** The driver must poll for IPC requests from active subagents
and relay them to the user. The infrastructure already exists on both sides:

- Subagent side: `writeIpcFile()`, `readIpcFile()`, poll loop in
  `tools/ask.ts`
- Parent side: `readIpcFile()`, `writeIpcFile()`, `createAskResponse()`,
  `createCancelledResponse()` in `lib/ipc.ts`
- UI: `askSingleQuestionWithInlineNote()`, `askQuestionsWithTabs()` in
  `ui/ask/`

What's missing is the glue: the driver (or extension entry point) must run
a polling loop that:

1. Watches the active subagent's directory for `ipc.json`
2. Reads the request payload
3. Renders the ask UI using the existing ask components
4. Writes the response (or cancellation) back to `ipc.json`

This polling should be integrated into `spawnSubagent()` or run as a
concurrent loop alongside the child process. The subagent's `ipc.json`
path is known (it's the `subagentDir`).

### 10.5 Vestigial cleanup: `PlanRef.qrPhase`

**Problem.** `PlanRef` in `lib/dispatch.ts` retains a `qrPhase` field from
the old architecture. §9.2 acknowledged it as "unused but retained to avoid
touching the kept `dispatch.ts` file."

**Correction.** Remove `qrPhase` from `PlanRef`. The `PlanRef` interface
becomes:

```typescript
export interface PlanRef {
  dir: string | null;
}
```

The `PlanRef`/`SubagentRef` mutable-ref pattern itself is retained — it's a
necessary accommodation for pi's extension lifecycle (tools register at init
before runtime state is available).

### 10.6 Widget redesign specification

**Problem.** §5.9 describes a "ground-up redesign" without specifying the
widget's data model, layout, or interaction model. The existing
`WidgetController` is designed for the old 3-phase pipeline and is
disconnected from the driver.

**Specification.** The widget provides three capabilities: status display,
spec review interaction, and escalation handling.

#### 10.6.1 Status display

The widget shows the full epic lifecycle state during execution:

- **Story list with status indicators.** All stories listed with their
  current status (`pending`, `selected`, `planning`, `executing`,
  `verifying`, `done`, `retry`, `escalated`, `skipped`). Visual indicators
  (icons or color) distinguish terminal states from active states.

- **Active subagent activity.** Which role is currently running (e.g.,
  "Executor: S-002"), which step it's on (e.g., "Step 2/3: Implementation"),
  and how long it's been running.

- **Full scrollable log tail.** The active subagent's event stream rendered
  as a scrollable log. Shows tool calls, file operations, bash commands,
  and koan tool invocations. Uses the existing `readRecentLogs()` and
  `LogLine` infrastructure from `audit.ts`, but without a fixed count
  limit — the widget streams the full tail.

- **Autonomous decision count.** A counter showing how many `[autonomous]`
  decisions the orchestrator has made since the last human interaction.
  Gives the user a sense of how much the system has diverged from the
  original spec.

Data source: the driver polls `state.json` (per-subagent projection) and
`events.jsonl` (log stream) from the active subagent's directory. The
existing `readProjection()` and `readRecentLogs()` functions provide the
read path.

#### 10.6.2 Spec review gate

After decomposition, the driver presents story sketches for human approval.
The widget renders:

- The full list of stories from `epic.md` and `stories/*/story.md`
- Per-story controls: **approve**, **edit** (opens the story.md for inline
  editing), **remove** (marks story as skipped)
- A global **approve all** action
- The driver blocks until the user explicitly confirms

This replaces the current auto-approve stub in `driver.ts`.

#### 10.6.3 Escalation handling

When a story reaches `escalated` status, the widget presents the escalation
interactively instead of returning a summary string:

- **Problem description** from the `EscalationInfo.problem` field
- **Candidate approaches** listed with selection controls
- **Recommended approach** highlighted
- **Custom response** text input for free-form direction
- **Actions**: select a candidate, provide custom direction, or abort

The user's response is written back to the story's state and the driver
resumes execution. This integrates with the existing ask UI components
but is triggered by the driver's escalation detection, not by
`koan_ask_question`.

### 10.7 Remaining work summary

Items from this analysis that require implementation, in priority order:

| #   | Item                                        | Priority     | Rationale                                                      |
| --- | ------------------------------------------- | ------------ | -------------------------------------------------------------- |
| 1   | Parent-side IPC responder (§10.4)           | **Blocking** | Intake hangs without it — system cannot start                  |
| 2   | Story discovery via filesystem scan (§10.2) | **Blocking** | Driver finds zero stories without it                           |
| 3   | Dispatch simplification (§10.3)             | High         | Misleading API; clean rewrite should not carry dead config     |
| 4   | `PlanRef.qrPhase` removal (§10.5)           | High         | Vestigial field from old architecture                          |
| 5   | Widget: status display (§10.6.1)            | High         | No visibility into execution without it                        |
| 6   | Widget: spec review gate (§10.6.2)          | High         | Mandatory human gate currently auto-approved                   |
| 7   | Widget: escalation handling (§10.6.3)       | High         | Escalations currently dead-end                                 |
| 8   | Decomposer prompt update                    | Medium       | Remove any JSON-writing instructions; LLM writes markdown only |

### 10.8 §10 implementation completed

All 8 items from §10.7 have been implemented and verified. Build is clean
(`tsc --noEmit`: 0 errors, `npm test`: 26/26 pass). This section records
what was built, the quality review findings, and the fixes applied.

#### 10.8.1 New files

| File                               | Purpose                                                                                                                                                                                                                                                   |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/planner/lib/ipc-responder.ts` | Parent-side IPC responder. Polls `ipc.json` in the active subagent directory (300ms interval). Routes to `askSingleQuestionWithInlineNote` (single question) or `askQuestionsWithTabs` (multi-question). Writes response back. Terminates on AbortSignal. |
| `src/planner/ui/epic-widget.ts`    | `EpicWidgetController`. Story list with status icons, active subagent info (role, step, elapsed time), full scrollable log tail via `readRecentLogs()` / `readProjection()`. 1-second unref'd timer refreshes elapsed display. `destroy()` cleans up.     |
| `src/planner/ui/spec-review.ts`    | `reviewStorySketches()`. Interactive spec review gate. Presents each story with ✓/□ toggles. Space toggles skip, A approves all, Enter confirms. Returns `{ approved, skipped }`.                                                                         |
| `src/planner/ui/escalation-ui.ts`  | `presentEscalation()`. Presents escalation problem, lists candidate approaches for selection. User selects a candidate or aborts. Returns `{ action, resolution? }`.                                                                                      |
| `tests/story-discovery.test.ts`    | 5 tests for `discoverStoryIds`: missing directory, empty directory, sorted output, file filtering, deterministic sort order.                                                                                                                              |

#### 10.8.2 Modified files

| File                                       | Change                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/planner/lib/dispatch.ts`              | Removed `qrPhase` from `PlanRef`. Interface is now `{ dir: string \| null }`.                                                                                                                                                                                                                                                  |
| `src/planner/phases/scout/phase.ts`        | Config simplified to `{ epicDir }`. Removed `question`, `outputFile`.                                                                                                                                                                                                                                                          |
| `src/planner/phases/scout/prompts.ts`      | `scoutStepGuidance()` takes no args; role-specific context is in spawn prompt.                                                                                                                                                                                                                                                 |
| `src/planner/phases/decomposer/phase.ts`   | Config simplified to `{ epicDir }`. Removed `scoutFiles`.                                                                                                                                                                                                                                                                      |
| `src/planner/phases/decomposer/prompts.ts` | Step 1 guidance changed to prompt-aware text: "If scout reports were referenced in your initial instructions above, read them now." Works with or without scout files.                                                                                                                                                         |
| `src/planner/phases/planner/phase.ts`      | Config simplified to `{ epicDir, storyId }`. Removed `scoutFiles`.                                                                                                                                                                                                                                                             |
| `src/planner/phases/dispatch.ts`           | All three simplified phases use new constructors per §10.3.                                                                                                                                                                                                                                                                    |
| `src/planner/subagent.ts`                  | Added `ui?: ExtensionUIContext` to `SpawnOptions`. `spawnSubagent()` starts `runIpcResponder` concurrently when `ui` is present; aborts it on process exit. `spawnPlanner` no longer takes `scoutFiles`.                                                                                                                       |
| `src/planner/epic/state.ts`                | Added `discoverStoryIds(epicDir)` — scans `stories/*/` directories, returns sorted IDs.                                                                                                                                                                                                                                        |
| `src/planner/driver.ts`                    | Story discovery via `discoverStoryIds()` replacing LLM-written JSON. Spec review gate via `reviewStorySketches()`. Escalation handling via `presentEscalation()` with re-execution on resolution. `EpicWidgetController` lifecycle through the story loop. Planner failure skips executor, proceeds to post-exec orchestrator. |
| `extensions/koan.ts`                       | Passes `ctx.ui` directly to `runEpicPipeline` instead of a narrow notify-only proxy.                                                                                                                                                                                                                                           |

#### 10.8.3 Quality review findings and fixes

A quality review identified 2 major issues, 2 minor issues, 1 note, and
1 latent issue. All were fixed.

**Fix 1 (major): IPC responder stale question after subagent exit.**

The IPC responder's ask UI calls (`askSingleQuestionWithInlineNote`,
`askQuestionsWithTabs`) don't accept an `AbortSignal` — they block until
user interaction. When a subagent exits mid-question, the user sees a stale
prompt.

Fix: after each UI call returns, immediately check `signal.aborted`. If
aborted, write `createCancelledResponse` instead of the user's answer and
break the loop. The UI call still blocks (limitation of pi's ask API), but
the stale answer is never written back to the dead subagent's IPC file.

**Fix 2 (major): Escalation "Other" option silently aborts.**

The escalation UI presented "Other (type your own)" as a selectable
candidate. All `done()` calls passed `note: ""`, so selecting "Other"
triggered `return { action: "abort" }` — the story was silently skipped.
§10.6.3 specifies custom text input, but pi's `ui.custom` doesn't support
text prompts.

Fix: removed the "Other" option entirely. The escalation UI now presents
only the actual candidates from `EscalationInfo.candidates` plus an "Abort"
option. A comment documents that custom text input can be added when pi's
UI primitives support it.

**Fix 3 (minor): `discoverStoryIds` swallowed non-ENOENT errors.**

The catch-all returned `[]` for any error, including `EACCES` or I/O
failures. This made permission errors look like "no stories found."

Fix: narrowed the catch to `ENOENT` only. All other errors are re-thrown.

**Fix 4 (minor): Planner failure continued to executor.**

When `planResult.exitCode !== 0`, the driver logged the failure but still
spawned the executor with no plan file, wasting a full executor turn.

Fix: after planner failure, the driver skips the executor spawn entirely,
sets the story status to `verifying`, and spawns the post-execution
orchestrator. The orchestrator sees no code changes and can make a
retry/escalate verdict.

**Fix 5 (note): Spec review Esc comment.**

Comment said "Esc proceed with current selections (treated as
approve-all)" but actual behavior was "confirm current selections and
proceed" (which may include skipped stories). Fixed the comment.

**Fix 6 (latent): Decomposer step guidance vs spawn prompt.**

Step 1 guidance always emitted "(No scout reports were produced)" because
`scoutFiles` was removed from the phase constructor (§10.3). When scouting
is wired, the spawn prompt will mention scout files but step guidance would
contradict it.

Fix: replaced the conditional text with prompt-aware guidance: "If scout
reports were referenced in your initial instructions above, read them now.
If no scout reports were mentioned, proceed without them." Compatible with
both cases.

#### 10.8.4 Remaining limitations

| Limitation                                                                  | Why                                               | Mitigation                                                  |
| --------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------- |
| IPC responder ask UI blocks until user interacts, even after subagent death | pi's ask UI components don't accept `AbortSignal` | Post-call abort check prevents writing stale answers        |
| No custom text input on escalation                                          | pi's `ui.custom` doesn't support text prompts     | "Other" option removed; add back when primitives support it |
| Scout question generation still stubbed                                     | Not in §10 scope (deferred from §9.4)             | Decomposer/planner run without codebase context from scouts |

---

## 11. Rewrite Specification (2026-03-11)

This section is the authoritative specification for the clean rewrite. It
was produced from a full codebase analysis session that examined every
source file, the complete plan (§1–§10), and resolved all ambiguities,
open decisions, and risks through structured decision-making. Where this
section conflicts with earlier sections, this section governs.

### 11.1 Rewrite approach

**Architecture-clean, infrastructure-pragmatic.** All module boundaries
and APIs are redesigned from scratch. Working infrastructure internals
(IPC file protocol, EventLog/audit, pool semaphore, atomic write patterns)
are ported into the new shape rather than rewritten blind. No code is
carried over verbatim — every module should look purpose-built for the
new architecture.

### 11.2 Scout system redesign

**This is the largest architectural change from the original plan.**

#### 11.2.1 The `koan_request_scouts` tool

A new tool available to intake, decomposer, and planner roles. When called,
the subagent pauses (via IPC), the driver spawns scouts in parallel via
`pool()`, and results are returned to the calling agent.

```typescript
const ScoutTaskSchema = Type.Object({
  id: Type.String({ description: "Scout task ID, e.g. 'auth-libs'" }),
  role: Type.String({
    description: "Custom role for the scout, e.g. 'system architect'",
  }),
  prompt: Type.String({
    description: "What to find, e.g. 'Find all auth-related files in src/'",
  }),
});

const RequestScoutsSchema = Type.Object({
  scouts: Type.Array(ScoutTaskSchema, { minItems: 1 }),
});
```

The tool uses the same IPC mechanism as `koan_ask_question`: the subagent
writes a scout request to `ipc.json`, the parent-side IPC responder detects
it, spawns scouts via `pool()`, waits for completion, and writes the result
(scout output file paths) back to `ipc.json`. The subagent reads the paths
and can then read the scout findings files.

#### 11.2.2 Intake sequence change

The original plan had intake reading the conversation and asking questions
without codebase context. This meant intake was limited to spec-level
questions and missed grounded questions that prevent downstream surprises.

**New intake step sequence (3 steps):**

1. **Context extraction**: Read `conversation.jsonl`. Extract structure into
   `context.md` (topic index, file references, decisions, constraints,
   unresolved questions). Call `koan_complete_step`.
2. **Codebase scouting**: Based on the conversation's file references and
   topic areas, identify what needs exploring. Call `koan_request_scouts`
   with targeted questions. Call `koan_complete_step`.
3. **Gap analysis + questions**: Review the structured summary AND scout
   findings together. Identify gaps — including contradictions between user
   intent and codebase reality, missing dependencies, incorrect assumptions
   about what exists. Formulate questions. Present to user via
   `koan_ask_question`. Write answers to `decisions.md`. Call
   `koan_complete_step`.

This means `context.md` and `decisions.md` are grounded in codebase reality
from the start, and the user's answers are informed by what actually exists.

#### 11.2.3 Three scout phases

1. **Intake scouts** — broad codebase survey informed by conversation context.
   Enables grounded user questions.
2. **Decomposition scouts** — concern-area exploration for story splitting.
   Different questions from intake scouts.
3. **Per-story planning scouts** — current file state at execution time (may
   have changed from earlier story execution).

Each phase calls `koan_request_scouts` with its own set of questions. The
driver handles all scout spawning through the IPC responder.

#### 11.2.4 IPC protocol extension

The IPC file (`ipc.json`) gains a second message type:

```typescript
// Existing ask request
interface AskRequest {
  type: "ask";
  questions: QuestionItem[];
  response: AskResponse | null;
}

// New scout request
interface ScoutRequest {
  type: "scout-request";
  scouts: ScoutTask[];
  response: ScoutResponse | null;
}

interface ScoutResponse {
  findings: string[]; // File paths to scout output markdown files
  failures: string[]; // Scout IDs that failed (non-fatal)
}
```

The parent-side IPC responder checks the `type` field and routes to either
the ask UI flow or the scout spawn flow.

### 11.3 Tool inventory changes

#### 11.3.1 Eliminate `koan_escalate`

**Escalation is asking a question.** Remove `koan_escalate` as a separate
tool. When the orchestrator needs human input (verification failures,
out-of-plan deviations, ambiguities), it uses `koan_ask_question` directly.
The orchestrator gets the answer via IPC, then decides what to do (retry,
skip, etc.) and calls the appropriate state-transition tool.

This eliminates:

- The `escalated` story status
- `EscalationInfo` from `StoryState`
- `escalation-ui.ts` as a separate component
- The driver's special escalation routing path

The driver's routing simplifies:

- `retry` with budget remaining → re-execute
- `retry` with budget exhausted → driver asks user via IPC or sets `skipped`
- No `escalated` status to handle

#### 11.3.2 Add `koan_request_scouts`

New tool per §11.2.1. Added to the permission sets of intake, decomposer,
and planner roles.

#### 11.3.3 Revised tool inventory

| Tool                  | Purpose                                | Roles                       | State Transition       |
| --------------------- | -------------------------------------- | --------------------------- | ---------------------- |
| `koan_complete_step`  | Advance phase step                     | All                         | Internal step counter  |
| `koan_ask_question`   | Ask user a question (IPC)              | All except scout            | None (synchronous)     |
| `koan_request_scouts` | Request parallel codebase scouts (IPC) | Intake, decomposer, planner | None (synchronous)     |
| `koan_select_story`   | Pick next story                        | Orchestrator                | `pending` → `selected` |
| `koan_complete_story` | Mark story done                        | Orchestrator                | `verifying` → `done`   |
| `koan_retry_story`    | Mark for re-execution                  | Orchestrator                | `verifying` → `retry`  |
| `koan_skip_story`     | Mark story skipped                     | Orchestrator                | `pending` → `skipped`  |

### 11.4 Revised state machine

The `escalated` status is removed. Retry budget exhaustion is handled by
the driver notifying the user (or skipping), not by a separate status.

```
pending ──[koan_select_story]──► selected
   │                                │
   │                          (driver: fixed)
   │                                │
   │                         planning ──► executing ──► verifying
   │                                                      │
   │                              ┌───────────────────────┤
   │                              │                       │
   │                    [complete_story]            [retry_story]
   │                              │                       │
   │                              ▼                       ▼
   │                            done                    retry
   │                                                      │
   │                                               (driver: budget
   │                                                check, re-exec
   │                                                or skip+notify)
   │                                                      │
   │                                                 executing
   │                                                      │
   │                                                   verifying
   │
   └──[koan_skip_story]──► skipped
```

Valid source statuses per tool (enforced — see §11.12):

| Tool                  | Valid source statuses |
| --------------------- | --------------------- |
| `koan_select_story`   | `pending`, `retry`    |
| `koan_complete_story` | `verifying`           |
| `koan_retry_story`    | `verifying`           |
| `koan_skip_story`     | `pending`             |

### 11.5 Architectural decisions

#### 11.5.1 BasePhase class

Extract a `BasePhase` class with the common lifecycle: event hook
registration, step progression, permission gating, audit emission.
Subclasses define only their step definitions (names, guidance functions)
and system prompt. This eliminates ~40 lines of duplicated skeleton per
phase.

#### 11.5.2 RuntimeContext (replaces mutable refs)

Replace `PlanRef` + `SubagentRef` + `WorkflowDispatch` with a single
`RuntimeContext` object:

```typescript
interface RuntimeContext {
  epicDir: string | null;
  subagentDir: string | null;
  onCompleteStep: ((thoughts: string) => string | null) | null;
}
```

Set once during `before_agent_start`. All tools read from this single
object. Fewer moving parts than three separate mutable refs.

#### 11.5.3 Template-based spawn prompts

Define explicit prompt templates per role in `prompts.ts`. Spawn functions
fill templates with runtime data (epicDir, storyId, scout paths, etc.).
The spawn prompt carries contextual information; phase step guidance carries
structural instructions. Both are combined in the subagent's context via
the append pattern.

#### 11.5.4 status.md schema

Templated sections for consistent orchestrator reads:

```markdown
# Status: <status>

## Last Action

<what happened and when>

## Verification Summary

<pass/fail details from verify.md checks>

## Notes

<propagation notes, autonomous decisions, context for next invocation>
```

#### 11.5.5 Story ID format

`S-001-auth-provider` — numbered + descriptive. Sortable and human-readable.
The decomposer prompt instructs this format. The driver discovers by
filesystem scan and is format-agnostic.

### 11.6 Driver changes

#### 11.6.1 Widget active polling

The driver runs a concurrent interval (2s) during subagent execution that
reads the subagent's `events.jsonl` projection via `readProjection()` and
updates the widget with step progress + log tail. The polling interval is
unref'd so it doesn't prevent process exit.

#### 11.6.2 Pre-create `stories/` directory

Before spawning the decomposer, the driver creates the `stories/` directory
under the epic dir. The decomposer's `write` tool creates per-story
subdirectories when writing `story.md` files.

#### 11.6.3 Simplified routing (no escalation path)

```typescript
function routeFromState(stories: StoryState[]): RoutingDecision {
  // 1. retry with budget → re-execute
  // 2. retry without budget → skip + notify user
  // 3. selected → execute (plan → run → verify)
  // 4. all terminal → complete
  // 5. none of above → error
}
```

#### 11.6.4 Binary error recovery

Exit code 0 vs non-zero. The orchestrator (post-exec) interprets what went
wrong. The driver routes based on the resulting state, not failure details.

### 11.7 Post-execution propagation

The orchestrator's post-execution step 3 (propagation) examines:

- `plan.md` — what was intended
- `verify.md` — what passed/failed
- `git diff --stat` — summary of what files changed and how much

This is enough to identify scope overlap with remaining stories without
reading full diffs. The orchestrator uses `write` to update affected
`story.md` files and appends to `decisions.md` with `[autonomous]` marker.

### 11.8 Conversation format

Keep raw JSONL export (`conversation.jsonl`). Accept pi-version coupling.
Intake prompt instructs the LLM to extract user/assistant messages and
ignore internal SessionManager entries (header, compaction, etc.).

### 11.9 Permission model

`bash` remains in `READ_TOOLS` (always allowed). This is an accepted
limitation — prompt engineering prevents abuse, enforcement is best-effort.
Document clearly in permission module comments.

`koan_request_scouts` is added to intake, decomposer, and planner
permission sets.

### 11.10 IPC design

Keep single-file IPC (`ipc.json` per subagent). Correct for sequential
execution. Redesign when parallel story execution is implemented. The
file format is extended with a `type` field to distinguish ask requests
from scout requests (§11.2.4).

### 11.11 Testing strategy

**Property-based state machine tests.** Verify:

- All valid story status transitions (per §11.4 table)
- Routing decisions for all state combinations
- Permission matrices (role × tool × expected result)

Skip IO-heavy integration tests. The system is inherently hard to test
end-to-end due to LLM non-determinism. Focus on the deterministic
boundaries (state machine, routing, permissions, tool validation).

### 11.12 Tool state-transition validation

**Enforce all transitions.** Every orchestrator tool validates source
status against the state machine (§11.4). Invalid transitions are rejected
with clear error messages including current status and valid source
statuses for the tool.

### 11.13 Convention resources

Keep `resources/conventions/` but defer integration. Preserve the files;
decide how to use them in executor/planner prompts after the core rewrite
is stable.

### 11.14 Remaining accepted limitations

| Limitation                                                        | Why                                           | Mitigation                                           |
| ----------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------- |
| IPC ask UI blocks until user interacts, even after subagent death | pi's ask API doesn't accept AbortSignal       | Post-call abort check prevents writing stale answers |
| bash in READ_TOOLS bypasses write path-scoping                    | Distinguishing read/write bash is intractable | Prompt engineering; document clearly                 |
| Conversation format coupled to pi internals                       | No stable export API                          | Intake prompt handles extraction                     |
| Single-file IPC won't scale to parallel execution                 | Sequential execution for now                  | Redesign when parallel is implemented                |

---

## 12. Post-Implementation Fixes — Scope & Lifecycle Mismatches (2026-03-12)

Post-implementation review and problem analysis (user reported the epic
widget not appearing during intake) uncovered 11 scope/lifecycle/naming
mismatches in the rewritten codebase. The root pattern: the rewrite built
types, infrastructure, and UI surfaces at epic breadth but only wired them
into the story execution loop (Phase B). Phase A (intake → decomposition →
spec review) runs with no persistent visual feedback.

This section specifies the fixes. They are grouped into four clusters (A–D)
ordered by dependency — each cluster can be implemented as one commit.

### 12.1 Cluster A — Lift observation scope to epic lifetime

**Root problem:** `EpicWidgetController` is created inside `runStoryLoop()`
(Phase B), not at the start of `runEpicPipeline()`. Phase A subagents
(intake, decomposer) write `EventLog` entries but nothing reads or displays
them. The user sees "Starting intake..." then nothing for the entire Phase A
duration.

**Findings addressed:** #1 (widget scope), #2 (polling asymmetry), #6
(autonomousDecisions phantom), original problem analysis (broken widget
rendering during Phase A).

#### 12.1.1 Widget lifecycle change

Move `EpicWidgetController` construction from `runStoryLoop()` to the top of
`runEpicPipeline()`, before the intake call. The widget instance is passed
into `runIntake()`, `runDecomposer()`, the spec review gate, and
`runStoryLoop()`.

```
runEpicPipeline()
  ├── create widget                    ← NEW: widget starts here
  ├── Phase A
  │   ├── runIntake(widget)            ← pass widget
  │   ├── runDecomposer(widget)        ← pass widget
  │   ├── discoverStoryIds → widget.update(stories)
  │   └── reviewStorySketches          ← widget suppressed during ui.custom()
  ├── Phase B
  │   └── runStoryLoop(widget)         ← receives widget, no longer creates it
  └── widget.destroy()
```

The widget naturally renders "No stories yet" (empty array) during Phase A —
`renderStoryList` already handles this. After `discoverStoryIds`, the widget
updates with the story list before spec review begins.

During `reviewStorySketches` (which uses `ui.custom()`, a modal takeover),
the widget is temporarily suppressed by pi's TUI — no code change needed.
After `ui.custom()` resolves, the widget resumes rendering.

#### 12.1.2 Phase A active polling

Wire `startActivePolling()` for intake and decomposer subagents. These
subagents already write `EventLog` (via `extensions/koan.ts:94-108`), so
`readProjection()` and `readRecentLogs()` work on their directories. The
change is purely in `runIntake()` and `runDecomposer()`:

```typescript
// runIntake — after creating subagentDir, before spawnIntake:
const started = Date.now();
widget?.update({
  activeSubagent: {
    role: "intake",
    step: 0,
    totalSteps: 3,
    stepName: "",
    startedAt: started,
  },
});
const stopPolling = widget
  ? startActivePolling(subagentDir, widget, started, "intake")
  : undefined;
// ... spawnIntake() ...
stopPolling?.();
```

Same pattern for `runDecomposer()` (totalSteps: 2).

#### 12.1.3 Phase indicator in widget

Add an `epicPhase` field to `EpicWidgetState`:

```typescript
interface EpicWidgetState {
  epicId: string;
  epicPhase: EpicPhase; // NEW — "intake" | "decomposition" | "review" | "executing" | "completed"
  stories: Array<{ storyId: string; status: StoryStatus }>;
  activeSubagent: ActiveSubagentInfo | null;
  logLines: LogLine[];
}
```

Display in the widget header: `Epic · {epicId} · {epicPhase}`.

The driver calls `widget.update({ epicPhase: "intake" })` before each phase
transition — same points where it already calls `saveEpicState`.

#### 12.1.4 Remove autonomousDecisions

Delete `autonomousDecisions` from `EpicWidgetState`, `EpicWidgetUpdate`,
the render badge, and all update callsites. No producer exists; add it back
when one does.

### 12.2 Cluster B — Dead infrastructure removal

**Root problem:** Orphaned code from the old architecture and phantom types
that suggest capabilities the system doesn't have.

**Findings addressed:** #3 (`scouting` phantom phase), #7 (orphaned
WidgetController), #10 (unused runtime temp dir).

#### 12.2.1 Delete `src/planner/ui/widget.ts`

900-line `WidgetController` from the old architecture. Zero imports anywhere
in the codebase. Pure dead code.

#### 12.2.2 Remove `"scouting"` from `EpicPhase`

The driver never assigns `"scouting"` — scouts are spawned by the IPC
responder within intake/decomposer/planner phases, not as a top-level driver
phase. Remove from the union type:

```typescript
// Before:
export type EpicPhase =
  | "intake"
  | "scouting"
  | "decomposition"
  | "review"
  | "executing"
  | "completed";

// After:
export type EpicPhase =
  | "intake"
  | "decomposition"
  | "review"
  | "executing"
  | "completed";
```

If a top-level scouting phase is added later, re-add it then.

#### 12.2.3 Remove runtime temp dir lifecycle

Delete `createRuntimeTempDir()` call and cleanup in `extensions/koan.ts`,
and delete `src/utils/runtime-temp.ts`. Neither is used by any pipeline
operation. Remove the corresponding test file (`tests/runtime-temp.test.ts`)
if it exists.

### 12.3 Cluster C — status.md / state.json synchronization

**Root problem:** The driver writes intermediate statuses (`planning`,
`executing`, `verifying`) to `state.json` but never updates `status.md`.
Any LLM or human reading `status.md` sees a stale status (e.g., still
"selected" while the story is actually executing).

**Finding addressed:** #4 (status.md / state.json divergence).

#### 12.3.1 New helper: `writeStatusMarkdown`

The AGENTS.md invariant prohibits LLMs from writing JSON — it does NOT
prohibit the driver from writing markdown. `status.md` is a projection of
`state.json`, analogous to how `EventLog` projects `state.json` from
`events.jsonl`.

Add to `src/planner/epic/state.ts`:

```typescript
export async function writeStatusMarkdown(
  epicDir: string,
  storyId: string,
  status: StoryStatus,
  lastAction: string,
): Promise<void> {
  const content = [
    `# Status: ${status}`,
    "",
    `**Last Action:** ${lastAction}`,
    "",
    "**Verification Summary:** (pending)",
    "",
    "**Notes:** —",
    "",
  ].join("\n");
  const filePath = path.join(epicDir, "stories", storyId, "status.md");
  await fs.writeFile(filePath, content, "utf8");
}
```

#### 12.3.2 Driver calls `writeStatusMarkdown` alongside `saveStoryState`

Every `saveStoryState` call in `driver.ts` that sets a driver-managed status
should also call `writeStatusMarkdown`:

| Call site                     | Status      | lastAction                                      |
| ----------------------------- | ----------- | ----------------------------------------------- |
| Before planner spawn          | `planning`  | `"Driver: starting planner"`                    |
| Before executor spawn         | `executing` | `"Driver: starting executor"`                   |
| Before post-exec orchestrator | `verifying` | `"Driver: starting verification"`               |
| Retry budget skip             | `skipped`   | `"Driver: retry budget exhausted (N attempts)"` |
| Retry re-execute              | `executing` | `"Driver: retry attempt N"`                     |

Orchestrator tools in `orchestrator.ts` already write richer `status.md`
with LLM-provided content (Last Action, Verification Summary, Notes). These
two writers are mutually exclusive in time — driver writes between subagent
spawns, orchestrator writes during its own execution.

### 12.4 Cluster D — Honest contracts

**Root problem:** Function signatures promise capabilities the callers
don't use, or silently degrade instead of failing.

**Findings addressed:** #5 (nullable UI dead paths), #8 (void'd config
params, storyId coercion).

#### 12.4.1 Assert UI at the boundary

Add an assertion at the top of `runEpicPipeline`:

```typescript
export async function runEpicPipeline(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  ui: ExtensionUIContext | null,
): Promise<{ success: boolean; summary: string }> {
  // koan_plan already guards !hasUI, but assert here to catch
  // any future call path that bypasses the guard.
  if (!ui) {
    return {
      success: false,
      summary: "Epic pipeline requires an interactive UI",
    };
  }
  // ...
}
```

Keep the `| null` type in the signature — inner functions use `widget?`
guards which are harmless and useful for testing. The assertion makes the
actual contract explicit at the entry point.

#### 12.4.2 Remove void'd config from phase constructors

`DecomposerPhase` and `ScoutPhase` constructors accept a `config` parameter
and immediately `void config`. Remove the parameter. If phase-specific
config is needed, it should come from `RuntimeContext` or constructor args
with specific types, not a generic object that gets discarded.

#### 12.4.3 Fail-fast on empty storyId in dispatch

In `dispatchPhase()`, lines 97 and 109 coerce null `storyId` to `""`:

```typescript
// Before:
storyId: config.storyId ?? "";

// After:
storyId: (() => {
  if (!config.storyId)
    throw new Error(`${role} phase requires --koan-story-id flag`);
  return config.storyId;
})();
```

Or extract a helper. An empty storyId creates malformed filesystem paths
like `stories//plan/plan.md` — this must fail immediately, not silently
produce broken paths.

### 12.5 Acknowledged: bash in READ_TOOLS

Per §11.9, `bash` in READ_TOOLS is an accepted limitation. The current
`permissions.ts` comment documents this. The actual scope is broader than
the per-role maps imply (bash is allowed for ALL roles via the early-return
READ_TOOLS check, not just orchestrator/executor as the role map suggests).

**Fix:** Update the comment in `permissions.ts` to accurately state that
`bash` is globally allowed via READ_TOOLS, not per-role. No behavioral
change.

### 12.6 Implementation order

Clusters have the following dependencies:

```
B (dead code removal) ← independent, do first for clean baseline
    ↓
A (widget lifecycle)  ← depends on B (scouting phase removed from EpicPhase)
    ↓
C (status.md sync)    ← independent of A, but cleaner after A
    ↓
D (honest contracts)  ← independent, do last (smallest changes)
```

Recommended order: **B → A → C → D**.

### 12.7 Verification

After all fixes:

- `npx tsc --noEmit` → zero errors
- `npm test` → all pass (test count may decrease from removing runtime-temp tests)
- Widget appears immediately when `koan_plan` starts (manual verification)
- Widget shows phase transitions during intake and decomposition
- `status.md` reflects `planning`/`executing`/`verifying` during subagent runs
- No `scouting` in EpicPhase, no `autonomousDecisions` in widget, no `widget.ts`
- `dispatchPhase` throws on empty storyId for planner/executor
