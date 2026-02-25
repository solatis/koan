# Koan Design Decisions & Invariants

Authoritative record of design decisions, invariants, and lessons learned
across the koan project. Distilled from 6 conversations (Feb 10-13 2026),
the master plan (plans/2026-02-10-init.md), and the approved tool registry
plan (~/.claude/plans/fluffy-hopping-zebra.md).

---

## Fundamental Invariants

### INV-1: Inversion of Control

Scripts drive the LLM, not LLM drives scripts. The extension
programmatically feeds prompts, collects output, and enforces constraints.
The LLM is a worker, not a coordinator. This is the entire reason koan
exists -- the Claude Code skill model has the LLM in the driver's seat,
which causes unreliable workflow execution.

### INV-2: Need-to-Know Principle

The LLM always operates on a need-to-know basis. When given the choice
between exposing more or less information, always choose less. This is
a permanent invariant.

Concrete implications:

- No implementation details in prompts (temp dirs, state file paths,
  orchestrator internals, phase routing)
- No full plan state when partial suffices (QR reviewer for design does
  not see code plan or docs plan)
- No accumulated history across phases (subagents start fresh)
- No meta-instructions about the workflow ("you are step 3 of 14")
- No defensive over-specification of edge cases

### INV-3: Pi Tool Error Contract

Pi framework determines isError on ToolResultMessage from whether
tool.execute() THROWS, not from the return value. The returned isError
field is silently discarded (agent-loop.ts:316-357). To signal errors
from tools: always `throw new Error(msg)` -- never `return { isError: true }`.

---

## Architecture Decisions

### AD-1: Two LLM Interaction Levels

- `sendUserMessage()` in parent session: ONLY for context capture. The
  session LLM is the only entity with the conversational understanding.
  A fresh LLM reading a serialized transcript loses implicit context.
- `spawn()` subagent: for all substantial work (architect, developer,
  writer, QR decomposer, QR reviewer).
- `complete()` from pi-ai: NOT used in koan. No direct LLM calls
  without agent loop.

### AD-2: Self-Loading Extension Pattern

Same extension file (extensions/koan.ts) serves both modes:

- **Parent mode** (no --koan-role flag): registers /koan command, tools,
  and dispatch. Zero overhead in normal pi sessions.
- **Subagent mode** (--koan-role present): activates role-specific event
  hooks (state machine, tool enforcement, step prompts).

The extension detects which mode via flag presence at before_agent_start
time (not at init -- see AD-3).

### AD-3: CLI Flag Timing

Pi applies CLI flag values AFTER extension factory functions run
(main.ts:568). getFlag() returns defaults during factory time.
Subagent detection MUST happen in `before_agent_start`, not in the
factory function body. Uses closure-scoped `dispatched` boolean guard
to ensure one-shot dispatch.

### AD-4: Tool-Call-Driven Step Transitions (Uniform Pattern)

ALL step transitions use the koan_complete_step registered tool. The LLM
calls koan_complete_step -> tool execute() returns next step's prompt.
This works in both -p mode and interactive mode. sendUserMessage()
is only used for the initial trigger (/koan plan).

**KEY CORRECTION**: Early design (Feb 10) considered turn_end +
agent_end + sendUserMessage() chaining for step transitions. This was
ABANDONED because subagents in -p mode exit after the first agent loop
completes. Tool calls keep the agent loop alive within a single loop.

**ANTI-PATTERN**: agent_end + sendUserMessage for retry was removed.
sendUserMessage is fire-and-forget in the extension binding. In -p mode
(subagents), the process can exit before the retry completes. Even in
interactive mode, some models say "calling tool X now" as text without
emitting a tool_call block, causing agent_end to fire spuriously.

### AD-5: koan_complete_step Accepts Optional `thoughts`

The extension is stateful -- it knows exactly which step the LLM is on
via closure state. No step number parameter needed. The tool response
contains the next step's full prompt.

The optional `thoughts` parameter captures the model's work output
(analysis, findings, review) as a tool parameter instead of as text
output. This solves a cross-model compatibility issue: GPT-5-codex
cannot produce text + tool_call in the same response, so requiring
text output alongside a tool call caused it to narrate "Calling
koan_complete_step now" without emitting an actual tool_call block.

### AD-6: Tool Naming Conventions

Settled names (corrected from earlier iterations):

- `koan_complete_step` (was koan_next_step -- renamed to accept `thoughts`)
- `koan_store_context` (was koan_finalize_context)
- `koan_store_plan` was later REMOVED entirely (see AD-14)
- Prompts use "instructions" not "actions"

### AD-7: invoke_after Pattern Is Critical

Every step prompt MUST have a clear "invoke after" directive telling
the LLM to call koan_complete_step after completing the step's work.
Mirrors the reference planner's "NEXT STEP: Command: python3 -m ...
--step N" pattern. Without this, the LLM produces text-only responses
and the agent loop exits.

Implementation: formatStep() in src/planner/prompts/step.ts appends a
default invoke-after block. Steps can override with custom invokeAfter.

The "WHEN DONE" + "Do NOT call until" creates a two-part gate: the LLM
must do work before advancing. Unconditional imperatives ("Execute this
tool now.") cause immediate tool calls because empty-param tool calls
have zero friction.

### AD-8: Store Tools Need "Not Yet" Guidance

koan_store_context (and formerly koan_store_plan) are always registered
and visible to the LLM even in steps where they should NOT be called.
Their tool descriptions include "DO NOT call this tool until the step
instructions explicitly tell you to." This creates a prohibition/activation
pattern with step prompts.

### AD-9: Subagent Progress Tracking

Per-subagent state directory, NOT a single progress.json.
Structure: `<planDir>/subagents/<role>-<hex>/`
Contains: state.json, stdout.log, stderr.log.
ProgressReporter class manages state.json updates with trail.

### AD-10: Architect System Prompt

The architect's system prompt is loaded from ~/.claude/agents/architect.md
at runtime via loadPlanDesignSystemPrompt(). Injected via
before_agent_start returning { systemPrompt: ... }.

### AD-11: Plan Schema Self-Documentation via TypeBox

No 300-line schema prompt embedded in step 6. Tool parameter schemas
with rich TypeBox descriptions are sufficient for the LLM to discover
the schema through tool definitions. This is the "most elegant" approach
per user preference.

### AD-12: Context Capture Phases

Three sub-phases within context capture:

1. **Drafting**: LLM reflects on conversation. MAY use tools for "high
   value" targeted exploration (confirm API signature, check file existence).
   DO NOT explore speculatively. Confidence tagging: HIGH (direct evidence)
   vs LOW (extrapolating).
2. **Verifying**: Self-check. Completeness, accuracy, phrasing for
   downstream agents. No tools except koan_complete_step.
3. **Refining**: Pure tool invocation (koan_store_context). Up to 3
   attempts with validation feedback.

### AD-13: Default-Deny Tool Permissions

Centralized Map<phaseKey, Set<toolName>> in src/planner/tools/registry.ts.
Unknown tools blocked in all phases. READ_TOOLS (read, bash, grep, glob,
find, ls) always allowed. WRITE_TOOLS (edit, write) always blocked during
planning. Missing phase keys are denied.

Previous code had a "fails open" bug where tool_call handlers returned
undefined at the end of if-else chains, silently allowing unknown tools.

### AD-14: Disk-Backed Plan Mutations (No Finalize)

Each mutation tool: loadPlan(dir) -> mutate -> savePlan(plan, dir).
Atomic write. No in-memory accumulation + finalize pattern. The
koan_store_plan/koan_finalize_plan tool was REMOVED.

Root cause: the LLM was skipping intermediate mutation tools and calling
koan_store_plan directly. The "build in memory then finalize" pattern
makes intermediate tools feel like ceremony. Immediate disk writes give
visible results per tool call.

Every mutation tool returns descriptive feedback ("Added decision DL-003:
'Use polling'"). This prevents the LLM from skipping tools -- the LLM
needs evidence that each tool call produces results.

### AD-15: Module Ownership

- Context-capture prompts belong to the "orchestrator" (session.ts /
  context-capture.ts)
- Plan-design prompts belong to the "architect" (plan-design.ts /
  prompts/plan-design.ts)
- These are organizational decisions about which module owns which prompts

### AD-16: 6-Step Architect Workflow (plan-design execute)

1. Task Analysis & Exploration Planning
2. Codebase Exploration
3. Testing Strategy Discovery
4. Approach Generation
5. Assumption Surfacing
6. Milestone Definition & Plan Writing (plan mutation tools available)

Steps 1-5: only READ_TOOLS + PLAN_GETTER_TOOLS + koan_complete_step allowed.
Step 6: plan mutation tools unlocked.

---

## UI Decisions

### UI-1: Planning Widget Cards & Timeline Rail
- Chosen on Feb 25 2026 via planning-widget design deck (Stacked Modular Cards + Vertical Timeline Rail).
- Rationale: make terminal output feel like a coherent operations workspace (not plain log spam), keep active progress glanceable, and preserve enough structure to scale into future phases without redesigning the shell.
- Implementation guardrails:
  - Continue rendering through `canvasLine()` so the background fills full terminal width.
  - Keep consistent card padding and solid-border framing through shared `renderBox()` helpers.
  - Phase chips use stable semantic tokens (accent active, bold muted completed, muted pending, error failed).
  - Vertical rail remains width-bounded (~20 cols) so the right detail pane keeps enough budget for high-signal telemetry.
  - Detail footer (`Plan · id`) is pinned bottom via dynamic padding, independent of timeline density.
  - Planning body and latest-log body share one outer card, separated by an internal divider for better cohesion.

### UI-2: Latest Log as Deterministic Dense Grid
- Chosen on Feb 25 2026 via follow-up deck (`Declarative Shape Table` + `Two-Column Dense Grid`).
- Rationale: long-running sessions need more than tool names; users must see intent without reading full payloads. Deterministic ordering reduces scan friction and makes anomalies obvious over time.
- Contract:
  - Left column anchor is always tool name.
  - Right column is deterministic summary from shape-table formatters (ID-first ordering for recognized tools).
  - Unknown tools degrade to name-only output (generic fallback).
  - Arrays render as first-item-plus-count; free-form fields render as size-only metadata.
  - Getter tools include target metadata + response size (`resp:42L/3.1k`).
  - Repeated events remain repeated (no collapse), preserving temporal audit fidelity.
  - Column widths adapt to terminal width and observed tool-name lengths so detail space stays useful.
  - In integrated mode, latest-log columns are forced to the same split as the planning body (`timelineWidth` / `detailWidth`) to keep vertical alignment stable.
  - High-value rows may wrap to 2 lines only; deeper overflow is compacted with ellipsis to protect fixed card height.

### UI-3: QR Integrated Section (Not Sidecar)
- Chosen on Feb 25 2026 via follow-up deck (`Inline Integrated Section + Divider`).
- Rationale: QR is the acceptance loop, not optional telemetry. Rendering it as an inline first-class section prevents the "detached widget" feel and matches how users reason about plan quality over time.
- Contract:
  - QR is visible during Plan design (and contractually Plan execution), hidden only for Context gathering.
  - Iteration 1 enters `execute` immediately (same stage model as fix iterations); there is no separate `initializing` stage.
  - Section includes: phase + iter/mode metadata, phase rail, and counters (`done/total/pass/fail/todo`) in a compact metadata block.
  - Visual treatment uses inline sectioning + divider, not a nested bordered mini-card.
  - Geometry is fixed for scan consistency: header + rail + counters + divider.
  - Metadata uses a hard 64-char visible-width budget with progressive compaction (`exec/decomp/vfy`, `d/p/f/t`, `iN/M`) under narrow widths.
  - Counter line emphasizes severity (`fail` highlighted in error color) so blocking issues pop in long sessions.
  - Detail pane hierarchy is explicit: `Current step` label first, then step body, then QR section.

## Workflow Dispatch Architecture

### WorkflowDispatch (dispatch pattern)

Workflow tools (koan_complete_step, koan_store_context) are registered once
at init. Their execute() callbacks read from a mutable dispatch object.
Phases hook/unhook dispatch slots at activation/deactivation time.

hookDispatch() throws if a slot is already occupied -- prevents silent
misrouting when two phases try to claim the same tool.

### PlanRef (mutable reference)

All plan mutation tools share a mutable `{ dir: string | null }` set
when /koan plan creates a directory or when --koan-plan-dir is received.
Decouples tool registration (init-time) from directory creation (runtime).

### Pi Registers Tools at \_buildRuntime()

Pi snapshots tools during \_buildRuntime(). Tools registered after this
point are invisible to the LLM. All 44+ tools register unconditionally
at init; phases restrict access via tool_call blocking at runtime.

---

## What Is NOT Ported from Reference Planner

| Reference planner component             | Koan replacement                      |
| --------------------------------------- | ------------------------------------- |
| CLI mutation scripts (cli/plan.py)      | Pi extension tool registration        |
| Thin router pattern (shared/routing.py) | Orchestrator deterministic gate logic |
| File-based state_dir                    | In-memory state + appendEntry()       |
| Template dispatch                       | Direct process spawning               |
| Constraint enforcement via prompt       | tool_call event blocking              |
| Agent markdown definitions              | Self-loading extension pattern        |
| Question relay handler                  | Not implemented (may add later)       |

---

## Bugs & Lessons Learned

### BUG-1: LLM Conflates Tool Instructions with Plan Content

In context capture, the LLM captured tool usage instructions as
constraints (e.g. "Use read tool before modifying files; edit for
surgical changes"). These are irrelevant developer instructions, not
task constraints. Solution: prompts explicitly state "Only include
constraints that are specific to this task. Do not include general
tool usage instructions, coding style guides, or editor/IDE conventions."

### BUG-2: LLM Skips Mutation Tools

The LLM called koan_complete_step through steps 1-5, then at step 6 skipped
all mutation tools and called koan_store_plan directly. The in-memory
plan was empty. Root cause: mutation tools returned opaque JSON with no
feedback -- they felt like ceremony. Solution: remove finalize tool,
disk-backed mutations, descriptive feedback per tool call (AD-14).

### BUG-3: tool_call Handlers Fail Open

Original tool_call handlers returned undefined at end of if-else chains,
silently allowing any new tool. Solution: default-deny permissions map
(AD-13).

### BUG-4: isError Return Value Discarded

Pi discards the isError field from tool return values. Only throw/no-throw
determines error status. This caused silent failures where tools returned
{ isError: true } but the framework treated them as success. Solution:
always throw new Error(msg) for error conditions (INV-3).

### BUG-5: Weak invoke_after Causes Step Skipping

Original weak format ("Now call koan_next_step.") produced skipped steps.
The LLM called the tool immediately without doing work, because tool
calls with empty params have zero friction. Solution: strengthen to
"WHEN DONE: Call koan_complete_step with your findings in the `thoughts`
parameter. Do NOT call this tool until the work described in this step
is finished."

### BUG-6: Flag Detection at Init Time

Early implementation tried to detect --koan-role in the extension factory
function body. Flags are unavailable at that point (main.ts:568 sets them
after). Solution: move detection to before_agent_start with dispatched
guard (AD-3).

---

## Plan JSON Schema

Matches reference planner's Pydantic schema (shared/schema.py).
Types defined in src/planner/plan/types.ts.

Key entities: Plan, Decision, RejectedAlternative, Risk, Milestone,
CodeIntent, CodeChange, Wave, DiagramGraph, ReadmeEntry, Overview,
InvisibleKnowledge, PlanningContext.

Cross-reference validation: intent_ref -> intents, decision_ref ->
decisions, diagram edges source/target -> nodes, wave milestones -> milestone IDs.

---

## QR Block Pattern

Work -> Decompose -> Verify (parallel) -> Gate. Repeated per phase
(design, code, docs). Gate is deterministic code, no LLM. Max 5
iterations. Force-proceed after limit.

QR tools: koan_qr_add_item, koan_qr_set_item, koan_qr_assign_group,
koan_qr_get_item, koan_qr_list_items, koan_qr_summary.

---

## Current Implementation State (Feb 13 2026)

Implemented:

- [x] Extension entry point with dual-mode detection
- [x] Context capture (3-phase: draft/verify/refine)
- [x] Plan-design architect subagent (6-step workflow)
- [x] 44+ plan mutation/getter tools with TypeBox schemas
- [x] Default-deny tool permissions (registry.ts)
- [x] WorkflowDispatch + PlanRef patterns
- [x] Subagent spawning with progress tracking
- [x] Disk-backed plan mutations (no finalize)
- [x] Plan validation (design + cross-references)

Not yet implemented:

- [ ] Developer role (plan-code phase)
- [ ] Technical writer role (plan-docs phase)
- [ ] QR decompose subagent
- [ ] QR verify subagent (parallel)
- [ ] QR gate routing
- [ ] Fix mode (re-spawn with QR failure report)
- [ ] State persistence (appendEntry + session_start restore)
- [ ] Plan execution workflow (milestone execution)
- [ ] /koan execute command
