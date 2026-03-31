# Workflow Orchestrator — Implementation Plan

## Problem Statement

Koan's pipeline manages an epic through eight phases:

```
intake → brief-generation → core-flows → tech-plan → ticket-breakdown
→ cross-artifact-validation → execution → implementation-validation
```

Only **intake** and **brief-generation** are currently implemented. The
remaining six phases exist as stubs — placeholder registrations in the phase
DAG that auto-advance when reached. Every run traverses every phase in exactly
this order. This creates two concrete problems.

**First, no flexibility.** A user who already understands the problem space
cannot skip brief generation. A user who wants to jump directly to core-flow
definition — bypassing the brief — has no way to express that intent. Adding
successor branches between phases would require forking the pipeline or adding
a tangle of conditional flags — both are maintenance traps.

**Second, no handoff.** When a phase completes, the pipeline silently advances.
The user sees no summary of what was accomplished, no explanation of what the
next phase will do, and no opportunity to adjust focus before work begins. This
matters most when phases accumulate context: after intake, the orchestrator
knows what was discussed; the next phase's LLM does not, unless context is
explicitly passed forward.

This plan replaces the hardcoded sequence with a **user-directed, orchestrator-
mediated loop**. After each phase completes, a workflow orchestrator agent
evaluates what was produced, surfaces a contextual status report with
recommended next phases, and holds a multi-turn conversation with the user to
agree on direction — with optional instructions that shape what the next phase
does. The orchestrator session appears inline in the ActivityFeed as a
continuation of the completed phase's activity, preserving full visual
continuity.

---

## Breaking Changes

This plan is a **breaking change** for existing epic directories. The
`EpicPhase` type renames `"brief"` → `"brief-generation"` and removes
`"decomposition"`, `"review"`, and `"executing"`. Existing `epic-state.json`
files containing these values are incompatible with the new phase registry.

**Migration:** Delete existing epic directories before deploying. No automated
migration is provided — this is pre-release software with no production state
to preserve.

The spec review gate (driver.ts lines 370–415) and all associated code are
**deleted**, not retained as dormant code. This includes `requestReview()` on
`WebServerHandle`, `ReviewStory`/`ReviewResult` types in `server-types.ts`,
the `ReviewForm` component, the `/api/review` POST endpoint, the `"review"`
SSE event type, and review-related store state. This functionality was
development scaffolding; a future `cross-artifact-validation` phase will use a
different mechanism.

---

## Phase Registry

### Canonical Phases

Eight phases form the complete epic lifecycle. Each phase has a well-defined
purpose, a set of artifacts it produces, and a set of artifacts it consumes.
The `EpicPhase` type is the single source of truth; adding or removing a phase
means updating this type and the transition DAG.

| Phase                       | Purpose                                                                                                              | Status      |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------- |
| `intake`                    | Multi-round codebase exploration and structured Q&A to align on requirements. Produces `landscape.md`.               | Implemented |
| `brief-generation`          | Distill intake context into a compact product-level epic brief. Produces `brief.md`.                                 | Implemented |
| `core-flows`                | Define user journeys with sequence diagrams. Produces `core-flows.md`.                                               | Stub        |
| `tech-plan`                 | Specify three-section technical architecture: approach, data model, component architecture. Produces `tech-plan.md`. | Stub        |
| `ticket-breakdown`          | Generate story-sized implementation tickets with dependency diagrams. Produces ticket files.                         | Stub        |
| `cross-artifact-validation` | Validate cross-boundary consistency across all spec artifacts. May edit specs to reconcile.                          | Stub        |
| `execution`                 | Implement tickets through a supervised batch process with verification and commit gates.                             | Stub        |
| `implementation-validation` | Post-execution review evaluating alignment and correctness against specs.                                            | Stub        |

`completed` is a terminal marker, not an active phase. The pipeline sets
`phase: "completed"` after the last phase succeeds.

### Stub Phases

Stub phases register in the DAG and the `EpicPhase` type but perform no work.
When the driver reaches a stub phase, it:

1. Saves the phase to `epic-state.json`
2. Pushes the phase to the web UI
3. Logs a placeholder message: `"Phase {phase} is a placeholder — auto-advancing"`
4. Immediately advances to the next phase per the DAG

This design lets the full phase registry and DAG exist from day one. The
orchestrator, UI pill strip, and documentation reference all eight phases
consistently. Implementing a phase later means replacing its stub entry in
the driver — no structural changes to routing, permissions, or the UI.

### Type Definition

```typescript
export type EpicPhase =
  | "intake"
  | "brief-generation"
  | "core-flows"
  | "tech-plan"
  | "ticket-breakdown"
  | "cross-artifact-validation"
  | "execution"
  | "implementation-validation"
  | "completed";
```

---

## Design Decisions (Resolved)

| #   | Decision                                         | Resolution                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | How do user instructions reach the next phase?   | Via `task.json` — the orchestrator commits a decision including optional instructions; the driver reads it and injects `phaseInstructions` into the next phase's task manifest. The phase's step 1 guidance template surfaces it as additional context.                                                                                                                                                     |
| 2   | When is the orchestrator skipped?                | When the DAG shows exactly one valid successor. No orchestrator process is spawned for deterministic transitions — the driver auto-advances at zero cost.                                                                                                                                                                                                                                                   |
| 3   | How does the workflow decision render in the UI? | Inline in the ActivityFeed as a continuation of the completed phase's activity. The phase's final log lines are frozen and dimmed; a visual separator marks the start of the orchestrator session; the orchestrator's tool calls stream below; and when `koan_propose_workflow` fires, a `WorkflowChat` component opens at the bottom of the feed showing the full multi-turn conversation. No mode switch. |
| 4   | What context does the orchestrator receive?      | The driver writes `workflow-status.md` before spawning — a markdown file listing completed phases, artifact paths, and the available next phases. The orchestrator reads this plus all existing artifacts.                                                                                                                                                                                                  |
| 5   | How does the phase registry work?                | `EpicPhase` is a TypeScript union expanded with new values as phases are added. The transition DAG is a plain constant — easy to read, easy to update, TypeScript-checkable.                                                                                                                                                                                                                                |

---

## Phase Transition DAG

The DAG defines which phases can legally follow which. Successor order encodes
recommendation priority: the first entry is the most-recommended default path.

The DAG is the **single source of truth** for what transitions are valid. The
driver uses it to decide whether to auto-advance or spawn the orchestrator. The
`koan_set_next_phase` tool validates against it before writing state, so the
orchestrator cannot commit an illegal transition. **The DAG itself does not
change** when promoting a stub to a real implementation — the phase name is
already in it. But the routing infrastructure requires coordinated updates;
see the Phase Promotion Checklist below.

```typescript
const PHASE_TRANSITIONS: Record<EpicPhase, EpicPhase[]> = {
  intake: ["brief-generation", "core-flows"], // 2 successors → orchestrator
  "brief-generation": ["core-flows"], // 1 successor → auto-advance
  "core-flows": ["tech-plan"], // 1 successor → auto-advance
  "tech-plan": ["ticket-breakdown"], // 1 successor → auto-advance
  "ticket-breakdown": ["cross-artifact-validation"], // 1 successor → auto-advance
  "cross-artifact-validation": ["execution"], // 1 successor → auto-advance
  execution: ["implementation-validation"], // 1 successor → auto-advance
  "implementation-validation": ["completed"], // 1 successor → auto-advance
  completed: [], // terminal
};
```

The `intake` phase has two successors: `brief-generation` (recommended default)
and `core-flows` (skip brief). After intake completes, the workflow orchestrator
spawns and presents the user with a choice. Even though `core-flows` is a stub
phase that auto-advances, this transition exercises the full orchestrator
path — IPC, UI, decision persistence — in production from day one.

Future DAG expansions can add more multi-successor transitions as phases are
implemented. The orchestrator infrastructure requires no changes — only the
DAG constant is updated when adding successor edges.

### Phase Promotion Checklist

When promoting a stub phase to a real implementation, the following changes
are required. The DAG itself does not change (the phase name is already in it).

| #   | File                                  | Change                                                                       |
| --- | ------------------------------------- | ---------------------------------------------------------------------------- |
| 1   | `lib/phase-dag.ts`                    | Add entry to `IMPLEMENTED_PHASES` set                                        |
| 2   | `types.ts`                            | Add new `SubagentRole` value and `ROLE_MODEL_TIER` entry                     |
| 3   | `lib/task.ts`                         | Create task interface variant; add to `SubagentTask` union                   |
| 4   | `lib/permissions.ts`                  | Add `ROLE_PERMISSIONS` entry for the new role                                |
| 5   | `driver.ts`                           | Add role mapping to `PHASE_ROLE`                                             |
| 6   | `phases/{phase}/phase.ts`             | Create phase class extending `BasePhase`                                     |
| 7   | `phases/{phase}/prompts.ts`           | Create system prompt + step guidance; thread `phaseInstructions` into step 1 |
| 8   | `phases/dispatch.ts`                  | Add case for the new role                                                    |
| 9   | `extensions/koan.ts`                  | Register any new phase-specific tools                                        |
| 10  | `web/js/components/StatusSidebar.jsx` | (Optional) Add dedicated status widget                                       |

---

## Architecture

### New Components

```
src/planner/
├── lib/
│   └── phase-dag.ts                        # Transition DAG + DAG query functions
├── phases/
│   └── workflow-orchestrator/
│       ├── phase.ts                        # WorkflowOrchestratorPhase extends BasePhase
│       └── prompts.ts                      # System prompt + step guidance
├── tools/
│   └── workflow-decision.ts               # koan_propose_workflow + koan_set_next_phase
├── lib/
│   ├── ipc.ts                             # + WorkflowDecisionIpcFile type + factory
│   ├── ipc-responder.ts                   # + handleWorkflowDecisionRequest dispatch
│   ├── permissions.ts                     # + "workflow-orchestrator" role
│   └── task.ts                            # + WorkflowOrchestratorTask + phaseInstructions
├── epic/
│   ├── types.ts                           # + WorkflowDecisionState
│   └── state.ts                           # + read/write workflow decision helpers
├── web/
│   ├── server.ts                          # + requestWorkflowDecision() + POST endpoint
│   │                                      # + freezeLogs() + frozen-logs SSE event
│   ├── server-types.ts                    # + event types + WebServerHandle methods
│   └── js/
│       ├── store.js                       # + workflowChat + frozenLogs state + handlers
│       ├── sse.js                         # + 'workflow-decision', 'frozen-logs' routing
│       └── components/
│           └── ActivityFeed.jsx           # + frozen zone + separator + WorkflowChat
├── driver.ts                              # Refactor: phase loop + orchestrator spawning
└── types.ts                              # Updated EpicPhase + "workflow-orchestrator" role
```

### Modified Components

| File                                  | Change                                                                                                                                                                                             |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types.ts`                            | Replace `EpicPhase` with 8 phases + `completed`. Add `"workflow-orchestrator"` to `SubagentRole` and `ROLE_MODEL_TIER` (strong).                                                                   |
| `lib/task.ts`                         | Add `WorkflowOrchestratorTask` variant; add optional `phaseInstructions?: string` to `SubagentTaskBase`.                                                                                           |
| `lib/permissions.ts`                  | Add `"workflow-orchestrator"` role entry.                                                                                                                                                          |
| `lib/ipc.ts`                          | Add `WorkflowDecisionIpcFile` to `IpcFile` union; add `"workflow-decision"` branch to `pollIpcUntilResponse`.                                                                                      |
| `lib/ipc-responder.ts`                | Add `handleWorkflowDecisionRequest` handler; add dispatch case in `runIpcResponder`.                                                                                                               |
| `phases/dispatch.ts`                  | Add `"workflow-orchestrator"` case: narrow task to `WorkflowOrchestratorTask`, extract config, construct `WorkflowOrchestratorPhase`.                                                              |
| `driver.ts`                           | Replace linear `intake → brief-generation → …` sequence with DAG-driven loop. Add stub handling for unimplemented phases. Add headless guard. Call `freezeLogs()` before spawning orchestrator.    |
| `web/server.ts`                       | Add `requestWorkflowDecision()`, POST `/api/workflow-decision`, `frozen-logs` SSE push + replay, `"workflow-decision"` branch in `replayState()`.                                                  |
| `web/server-types.ts`                 | Add `WorkflowDecisionEvent`, `FrozenLogsEvent`, `WorkflowDecisionFeedback`, `freezeLogs` + `requestWorkflowDecision` to `WebServerHandle`. Add `"workflow-decision"` to `PendingEntry.type` union. |
| `web/js/store.js`                     | Add `frozenLogs`, `workflowChat` slices + handlers; clear on phase transition and pipeline end.                                                                                                    |
| `web/js/sse.js`                       | Add `'workflow-decision'`, `'workflow-decision-cancelled'`, `'frozen-logs'` routing.                                                                                                               |
| `web/js/components/App.jsx`           | Pass `token` prop to `ActivityFeed`; `workflowChat` must not affect `isInteractive`.                                                                                                               |
| `web/js/components/ActivityFeed.jsx`  | Accept `token` prop; render frozen zone + separator + live logs + `WorkflowChat`.                                                                                                                  |
| `web/js/components/PillStrip.jsx`     | Update `PHASES` and `PHASE_ORDER` arrays for the 8 phases.                                                                                                                                         |
| `web/js/components/StatusSidebar.jsx` | Update `PhaseStatus` switch for new phase identifiers. Add generic status for stub phases. Remove `phase === 'review'` branch from `GenericStatus`.                                                |
| `web/js/components/PhaseContent.jsx`  | Remove review rendering branch (part of spec review gate deletion).                                                                                                                                |
| `web/css/components.css`              | Styles for frozen logs, orchestrator separator, `WorkflowChat`.                                                                                                                                    |
| `extensions/koan.ts`                  | Register new tools.                                                                                                                                                                                |
| All phase step 1 guidance functions   | Thread `phaseInstructions` into step 1 context when present.                                                                                                                                       |

---

## Detailed Component Designs

### 1. Types and Task Manifest

`EpicPhase` is the canonical phase registry. It replaces the previous
placeholder union with the full lifecycle:

```typescript
export type EpicPhase =
  | "intake"
  | "brief-generation"
  | "core-flows"
  | "tech-plan"
  | "ticket-breakdown"
  | "cross-artifact-validation"
  | "execution"
  | "implementation-validation"
  | "completed";
```

`SubagentRole` gains `"workflow-orchestrator"` with `"strong"` model tier. This
mirrors the existing `"orchestrator"` role's tier assignment — workflow-level
decisions require the same reasoning quality as story-level orchestration.

`SubagentTaskBase` gains an optional `phaseInstructions` field. Making it part
of the base (rather than a variant-specific field) means every phase receives
it uniformly, and the driver can set it without branching on role. Phases that
receive no instructions simply see `undefined` and skip the context injection.
Because `phaseInstructions` is optional and JSON.stringify omits `undefined`
values, existing task construction sites (`{ role, epicDir }`) require no
changes — they remain valid subtypes.

```typescript
export type SubagentRole =
  | "intake"
  | "scout"
  | "decomposer"
  | "orchestrator"
  | "planner"
  | "executor"
  | "brief-writer"
  | "workflow-orchestrator";

export const ROLE_MODEL_TIER: Record<SubagentRole, ModelTier> = {
  // ... existing ...
  "workflow-orchestrator": "strong",
};
```

```typescript
/** Optional instructions from the workflow orchestrator's decision.
 *  Injected into step 1 guidance of the next phase when the user provides
 *  context during the workflow decision interaction (e.g. "focus on auth
 *  requirements"). Absent when the orchestrator is skipped or when the user
 *  gives no additional direction. */
interface SubagentTaskBase {
  role: SubagentRole;
  epicDir: string;
  phaseInstructions?: string;
}

export interface WorkflowOrchestratorTask extends SubagentTaskBase {
  role: "workflow-orchestrator";
  completedPhase: EpicPhase; // which phase just finished — for context
  availablePhases: EpicPhase[]; // valid successors from the DAG
}
```

### 2. Phase Transition DAG

**`lib/phase-dag.ts`** (new file):

```typescript
import type { EpicPhase } from "../types.js";

/** Valid successor phases for each phase. Order = recommendation priority.
 *  This is the single source of truth consulted by:
 *    - the driver (to decide whether to spawn the orchestrator)
 *    - koan_set_next_phase (to validate the committed transition)
 *    - WorkflowOrchestratorPhase step 2 guidance (lists available phases)
 *  Add new phases here; routing logic requires no other changes. */
export const PHASE_TRANSITIONS: Readonly<
  Record<EpicPhase, readonly EpicPhase[]>
> = {
  intake: ["brief-generation", "core-flows"],
  "brief-generation": ["core-flows"],
  "core-flows": ["tech-plan"],
  "tech-plan": ["ticket-breakdown"],
  "ticket-breakdown": ["cross-artifact-validation"],
  "cross-artifact-validation": ["execution"],
  execution: ["implementation-validation"],
  "implementation-validation": ["completed"],
  completed: [],
};

/** Phases that have a real implementation (subagent-backed).
 *  All other phases are stubs that auto-advance when reached. */
export const IMPLEMENTED_PHASES: ReadonlySet<EpicPhase> = new Set([
  "intake",
  "brief-generation",
]);

/** Returns valid next phases from the DAG. */
export function getSuccessorPhases(phase: EpicPhase): readonly EpicPhase[] {
  return PHASE_TRANSITIONS[phase] ?? [];
}

/** True when the driver can auto-advance without consulting the orchestrator.
 *  A single successor means the transition is unambiguous; spawning an
 *  orchestrator would add latency and LLM cost with no user value. */
export function isAutoAdvance(phase: EpicPhase): boolean {
  return getSuccessorPhases(phase).length === 1;
}

/** True when the phase has no subagent implementation and should be skipped. */
export function isStubPhase(phase: EpicPhase): boolean {
  return phase !== "completed" && !IMPLEMENTED_PHASES.has(phase);
}

/** Validates that a proposed transition is legal before committing.
 *  Called by koan_set_next_phase to prevent the orchestrator from
 *  hallucinating a phase name not in the DAG. */
export function isValidTransition(from: EpicPhase, to: EpicPhase): boolean {
  return getSuccessorPhases(from).includes(to);
}

/** Human-readable one-line description of each phase.
 *  Used by writeWorkflowStatus() and the orchestrator's step 2 guidance. */
export const PHASE_DESCRIPTIONS: Readonly<Record<EpicPhase, string>> = {
  intake:
    "Multi-round codebase exploration and structured Q&A to align on requirements",
  "brief-generation":
    "Distill intake context into a compact product-level epic brief",
  "core-flows": "Define user journeys with sequence diagrams",
  "tech-plan":
    "Specify technical architecture: approach, data model, component design",
  "ticket-breakdown":
    "Generate story-sized implementation tickets with dependency diagrams",
  "cross-artifact-validation":
    "Validate cross-boundary consistency across all spec artifacts",
  execution:
    "Implement tickets through a supervised batch process with verification",
  "implementation-validation":
    "Post-execution review evaluating alignment and correctness against specs",
  completed: "Pipeline complete",
};
```

### 3. IPC Type: `workflow-decision`

The workflow decision follows the same IPC protocol as `artifact-review`:
the subagent writes a request with `response: null`, polls until the parent
fills in the response, then deletes the file and returns the response text
to the LLM. This reuse is deliberate — the entire IPC machinery (atomic
writes, polling, idempotence guard, abort handling, SSE replay) is already
proven and requires no structural changes.

The response is **plain text**, not a structured selection, for the same reason
`artifact-review` uses plain text: a dedicated `selectedPhase` field would
force a two-branch protocol and require the tool to execute the branch
mechanically. Plain text lets the LLM interpret the user's intent, handle
ambiguous responses, and re-propose when the response is unclear. The
`koan_set_next_phase` call is the structured commitment; everything before it
is conversational.

**`lib/ipc.ts`** additions:

```typescript
export interface WorkflowPhaseOption {
  phase: string; // EpicPhase value
  label: string; // human-readable, e.g. "Write Epic Brief"
  context: string; // why this phase is useful right now
  recommended?: boolean;
}

export interface WorkflowDecisionPayload {
  statusReport: string; // markdown summary of current state
  recommendedPhases: WorkflowPhaseOption[];
  completedPhase: string; // the just-completed phase (not a history —
  // EpicState stores only the current phase)
}

// Matches the shape of ArtifactReviewResponse: id for correlation,
// respondedAt for debugging. Consistent with all other IPC response types.
export interface WorkflowDecisionResponse {
  id: string;
  respondedAt: string;
  feedback: string; // user's free-form text response
}

export interface WorkflowDecisionIpcFile {
  type: "workflow-decision";
  id: string;
  createdAt: string;
  payload: WorkflowDecisionPayload;
  response: WorkflowDecisionResponse | null;
}

// Updated union:
export type IpcFile =
  | AskIpcFile
  | ScoutIpcFile
  | ArtifactReviewIpcFile
  | WorkflowDecisionIpcFile;
```

**`pollIpcUntilResponse` requires a new branch.** The existing function has
explicit if-branches for each IPC type. Without a matching branch for
`"workflow-decision"`, the poll loop never detects the response and the pipeline
hangs indefinitely. Add the following alongside the existing `artifact-review`
branch:

```typescript
if (
  current.type === "workflow-decision" &&
  current.response !== null &&
  current.id === ipc.id
) {
  outcome = "answered";
  finalIpc = current;
  break;
}
```

The `createWorkflowDecisionRequest` factory follows the exact pattern of
`createArtifactReviewRequest`.

### 4. New Tools

**`tools/workflow-decision.ts`** (new file):

#### `koan_propose_workflow`

Presents the workflow decision to the user via IPC. Structurally identical to
`koan_review_artifact`: writes an IPC file, polls for the response, returns
the user's text. The orchestrator can call this tool multiple times — if the
user provides feedback rather than direction, the orchestrator addresses it
and calls the tool again. The loop terminates only when the orchestrator
commits via `koan_set_next_phase`.

Each call to `koan_propose_workflow` is a new, independent IPC round-trip. The
multi-turn conversation history is maintained client-side (see §8); from the
server and tool perspective every call is a fresh `workflow-decision` IPC file.

```typescript
// Parameters:
{
  status_report: string,
  recommended_phases: Array<{
    phase: string,
    label: string,
    context: string,
    recommended?: boolean
  }>
}
```

**Execution flow:**

1. Guard: return error if another IPC request is already pending
2. Read `completedPhase` from `task.json` (via `readTaskFile(ctx.subagentDir)`,
   narrowed to `WorkflowOrchestratorTask`) for UI context
3. Write `WorkflowDecisionIpcFile` to `ipc.json` (atomic tmp-rename)
4. `pollIpcUntilResponse()` at 500ms — blocks the LLM turn
5. Delete `ipc.json`, return the user's feedback text

#### `koan_set_next_phase`

Commits the phase transition decision. Analogous to `koan_select_story` for
phase-level routing: writes a structured decision file the driver reads after
the orchestrator exits.

```typescript
// Parameters:
{
  phase: string,
  instructions?: string
}
```

**Execution flow:**

1. Read `task.json` from `ctx.subagentDir` via `readTaskFile()`, narrow to
   `WorkflowOrchestratorTask` via `task.role === "workflow-orchestrator"`,
   obtain `availablePhases`. This is the directory-as-contract approach:
   structured inputs live in `task.json`, not in tool parameters or
   RuntimeContext fields. The tool reads at call time rather than caching in
   RuntimeContext to avoid adding orchestrator-specific fields to a shared
   carrier.
2. Validate `phase` is in `availablePhases`
3. Write `workflow-decision.json` atomically to **`ctx.subagentDir`**
4. Return confirmation text

The decision file lives in the subagent directory (not epicDir) to preserve
the directory-as-contract invariant: the subagent directory is the sole
interface between parent and child. The driver reads this file from the
orchestrator's subagentDir after the process exits, before any directory
cleanup.

**State file** (`{subagentDir}/workflow-decision.json`):

```json
{
  "nextPhase": "core-flows",
  "instructions": "Focus on auth requirements",
  "decidedAt": "2026-03-24T12:00:00.000Z"
}
```

**`WorkflowDecisionState`** (in `epic/types.ts`) — the TypeScript type for this file:

```typescript
/** Written by koan_set_next_phase to the subagent directory.
 *  Read by the driver after the orchestrator process exits.
 *  nextPhase is string (not EpicPhase) because it's read from JSON
 *  and validated via isValidTransition() before casting. */
export interface WorkflowDecisionState {
  nextPhase: string;
  instructions?: string;
  decidedAt: string;
}
```

**`readWorkflowDecision()`** (in `epic/state.ts`) — reads the decision file
after the orchestrator process exits:

```typescript
import type { WorkflowDecisionState } from "./types.js";

/** Read {subagentDir}/workflow-decision.json written by koan_set_next_phase.
 *  Returns null if absent (orchestrator crashed before committing) or
 *  malformed (should never happen — koan_set_next_phase writes valid JSON). */
export async function readWorkflowDecision(
  subagentDir: string,
): Promise<WorkflowDecisionState | null> {
  try {
    const raw = await fs.readFile(
      path.join(subagentDir, "workflow-decision.json"),
      "utf8",
    );
    return JSON.parse(raw) as WorkflowDecisionState;
  } catch {
    return null;
  }
}
```

### 5. WorkflowOrchestratorPhase

Extends `BasePhase`. Two steps per the single-cognitive-goal principle:
one step to gather context, one step to hold the user conversation and commit.
Merging these into a single step would allow the LLM to pre-plan its
recommendation while still reading artifacts — the steps must be isolated so
evaluation precedes proposal.

| Step | Name     | Purpose                                                                          |
| ---- | -------- | -------------------------------------------------------------------------------- |
| 1    | Evaluate | Read `workflow-status.md` and phase artifacts. Build mental model.               |
| 2    | Propose  | Call `koan_propose_workflow`. Handle feedback. Commit via `koan_set_next_phase`. |

**Step 2 validation gate** blocks `koan_complete_step` unless both
`koan_propose_workflow` and `koan_set_next_phase` have been called. The
proposal gate ensures the orchestrator cannot silently commit a phase
transition without presenting options to the user — the entire value
proposition of the orchestrator is user interaction. Uses `event.isError`
(not `event.error`) to match `ReviewablePhase`'s established convention:

```typescript
/** Config extracted from WorkflowOrchestratorTask by dispatch.ts.
 *  Keeps the constructor signature clean and type-safe. */
interface WorkflowOrchestratorConfig {
  completedPhase: EpicPhase;
  availablePhases: readonly EpicPhase[];
}

export class WorkflowOrchestratorPhase extends BasePhase {
  protected readonly role = "workflow-orchestrator";
  protected readonly totalSteps = 2;

  private readonly completedPhase: EpicPhase;
  private readonly availablePhases: readonly EpicPhase[];
  private proposalMade = false;
  private nextPhaseSet = false;

  constructor(
    pi: ExtensionAPI,
    config: WorkflowOrchestratorConfig,
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log, eventLog);
    this.completedPhase = config.completedPhase;
    this.availablePhases = config.availablePhases;

    pi.on("tool_result", (event) => {
      // event.isError matches ReviewablePhase convention — not event.error
      if (event.toolName === "koan_propose_workflow" && !event.isError) {
        this.proposalMade = true;
      }
      if (event.toolName === "koan_set_next_phase" && !event.isError) {
        this.nextPhaseSet = true;
      }
    });
  }

  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 2 && !this.proposalMade) {
      return (
        "You must call koan_propose_workflow to present options to the user " +
        "before committing a phase transition."
      );
    }
    if (step === 2 && !this.nextPhaseSet) {
      return (
        "You must call koan_set_next_phase before completing this step. " +
        "Call koan_propose_workflow again if you still need user input."
      );
    }
    // Delegate to BasePhase for step bounds checking and any future base validations.
    return super.validateStepCompletion(step);
  }
}
```

**Step 2 guidance** injects `availablePhases` from the task manifest into the
prompt so the orchestrator only proposes valid DAG transitions.

### 6. Driver Refactor

The linear sequence in `runPipeline()` is replaced with a DAG-driven loop.
`runWorkflowOrchestrator()` returns `{ nextPhase, instructions }` so
`phaseInstructions` flows cleanly as a return value rather than a mutable
closure variable.

Before spawning the orchestrator, the driver calls `webServer.freezeLogs()` to
snapshot the completed phase's activity into the frozen log buffer (see §8).
This preserves visual continuity: the phase's tool calls and thinking cards
remain visible as the orchestrator session begins below them.

**Stub phases** are handled by `runPhase()` — when `isStubPhase(phase)` returns
true, the driver logs a placeholder message and returns immediately without
spawning any subagent. This makes stubs zero-cost: no process spawn, no LLM
call, no web server tracking.

**Phase-to-role mapping** maps each implemented phase to its subagent role.
This replaces the previous approach where the role name was passed directly:

```typescript
/** Maps implemented phases to the subagent role that executes them.
 *  Stubs are not listed — they never spawn a subagent. */
const PHASE_ROLE: Partial<Record<EpicPhase, SubagentRole>> = {
  intake: "intake",
  "brief-generation": "brief-writer",
};
```

```typescript
async function runPipeline(epicDir, cwd, extensionPath, log, webServer) {
  let phase: EpicPhase = "intake";
  let pendingInstructions: string | undefined;

  while (phase !== "completed") {
    await saveEpicState(epicDir, { ...state, phase });
    webServer?.pushPhase(phase);

    if (isStubPhase(phase)) {
      log(`Phase "${phase}" is a placeholder — auto-advancing`, { phase });
      // Do NOT clear pendingInstructions here. Stubs don't consume
      // instructions — carry them forward to the next real phase.
    } else {
      const phaseOk = await runPhase(phase, epicDir, cwd, extensionPath, log, webServer, pendingInstructions);
      pendingInstructions = undefined; // consumed by the real phase
      if (!phaseOk) return { success: false, summary: `Phase "${phase}" failed` };
    }

    const successors = getSuccessorPhases(phase);
    if (successors.length === 0) break;

    if (isAutoAdvance(phase)) {
      phase = successors[0];
      continue;
    }

    // Multiple successors: requires user direction.
    // In headless mode (no webServer), the orchestrator cannot run because
    // koan_propose_workflow requires requestWorkflowDecision() on the server
    // and the IPC responder is not started. Auto-advance to the recommended
    // (first) successor to preserve CI correctness.
    if (!webServer) {
      log("No web server — auto-advancing to recommended phase (headless mode)", {
        from: phase, to: successors[0],
      });
      phase = successors[0];
      continue;
    }

    // Snapshot the completed phase's activity before spawning the orchestrator.
    // trackSubagent() for the orchestrator will replace the live log buffer;
    // freezeLogs() preserves the phase's final state for the frozen zone in
    // the ActivityFeed.
    webServer.freezeLogs();

    const decision = await runWorkflowOrchestrator(phase, successors, epicDir, ...);
    if (!decision) {
      return { success: false, summary: `Workflow orchestrator failed after "${phase}"` };
    }
    phase = decision.nextPhase;
    pendingInstructions = decision.instructions;
  }

  await saveEpicState(epicDir, { ...state, phase: "completed" });
  webServer?.pushPhase("completed");
}
```

**`runPhase()`** accepts `phaseInstructions?` and dispatches to the appropriate
subagent:

```typescript
async function runPhase(
  phase,
  epicDir,
  cwd,
  extensionPath,
  log,
  webServer,
  phaseInstructions?,
): Promise<boolean> {
  const role = PHASE_ROLE[phase];
  if (!role) {
    // Should never happen — isStubPhase() guards this in the loop above.
    throw new Error(`No role mapping for implemented phase: ${phase}`);
  }
  return runSimplePhase(
    role,
    epicDir,
    webServer,
    extensionPath,
    cwd,
    log,
    phaseInstructions,
  );
}
```

`runSimplePhase()` gains `phaseInstructions?` and includes it in the task:

```typescript
// role parameter widens from "intake" | "brief-writer" | "decomposer" to SubagentRole
// to accommodate future phase roles dispatched through PHASE_ROLE.
async function runSimplePhase(role: SubagentRole, epicDir, ..., phaseInstructions?) {
  const task = (phaseInstructions
    ? { role, epicDir, phaseInstructions }
    : { role, epicDir }) as SubagentTask;
  // ...
}
```

**`runWorkflowOrchestrator()`** returns the structured decision:

```typescript
async function runWorkflowOrchestrator(
  completedPhase: EpicPhase,
  availablePhases: EpicPhase[],
  epicDir: string,
  ...
): Promise<{ nextPhase: EpicPhase; instructions?: string } | null> {
  await writeWorkflowStatus(epicDir, completedPhase, availablePhases);

  const task: WorkflowOrchestratorTask = {
    role: "workflow-orchestrator",
    epicDir,
    completedPhase,
    availablePhases,
  };
  // Timestamp ensures no stale workflow-decision.json from a crashed run
  // is accidentally read on restart.
  const dir = await ensureSubagentDirectory(epicDir, `workflow-orch-${completedPhase}-${Date.now()}`);
  const id = `workflow-orchestrator-${completedPhase}`;
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };
  const result = await spawnTracked(id, id, "workflow-orchestrator", task, dir, undefined, opts, webServer);

  if (result.exitCode !== 0) {
    log("Workflow orchestrator failed", { exitCode: result.exitCode, completedPhase });
    return null;
  }

  const decision = await readWorkflowDecision(dir);
  if (!decision) {
    log("Workflow orchestrator exited without committing a decision", { completedPhase });
    return null;
  }
  if (!isValidTransition(completedPhase, decision.nextPhase as EpicPhase)) {
    log("Workflow orchestrator committed an invalid transition", {
      completedPhase, nextPhase: decision.nextPhase,
    });
    return null;
  }

  return { nextPhase: decision.nextPhase as EpicPhase, instructions: decision.instructions };
}
```

### 7. `phaseInstructions` Threading

Full data flow from user text to next-phase LLM context. There are **10 steps**
across 6 files:

```
 1. Orchestrator calls koan_set_next_phase({ phase: "core-flows", instructions: "Focus on auth" })
 2. Tool reads task.json from subagentDir → narrows to WorkflowOrchestratorTask → validates
 3. Tool writes workflow-decision.json to subagentDir: { nextPhase: "core-flows", instructions: "..." }
 4. runWorkflowOrchestrator() reads decision from subagentDir → returns { nextPhase, instructions }
 5. runPipeline() stores in pendingInstructions
 6. runPipeline() passes pendingInstructions to runPhase() → consumed and cleared
 7. runPhase() calls runSimplePhase() with phaseInstructions
 8. runSimplePhase() writes task.json: { role, epicDir, phaseInstructions: "..." }
 9. koan.ts (before_agent_start) reads task.json, sets ctx.phaseInstructions = task.phaseInstructions
10. Phase.getStepGuidance(1) reads this.ctx.phaseInstructions, appends as context block
```

**Step 9 is critical and requires changes to two existing files:**

**`lib/runtime-context.ts`** gains `phaseInstructions`:

```typescript
export interface RuntimeContext {
  epicDir: string | null;
  subagentDir: string | null;
  onCompleteStep: ((thoughts: string) => Promise<string | null>) | null;
  currentStep: number;
  eventLog: EventLog | null;
  phaseInstructions?: string; // ← new: from workflow orchestrator decision
  // Note: availablePhases is NOT in RuntimeContext — it is role-specific to
  // the workflow-orchestrator and accessed via readTaskFile() in the tool.
  // phaseInstructions IS here because it applies to ALL phases uniformly.
}
```

**`extensions/koan.ts`** (in `before_agent_start`, after `readTaskFile`):

```typescript
const task = await readTaskFile(subagentDir);
ctx.epicDir = task.epicDir;
ctx.subagentDir = subagentDir;
ctx.phaseInstructions = task.phaseInstructions; // ← new: thread into context
```

**Phase guidance functions** access via `this.ctx.phaseInstructions`:

```typescript
// In BriefWriterPhase.getStepGuidance:
protected getStepGuidance(step: number): StepGuidance {
  return briefWriterStepGuidance(step, this.ctx.epicDir!, this.ctx.phaseInstructions);
}

// In briefWriterStepGuidance:
function briefWriterStepGuidance(step: number, epicDir: string, phaseInstructions?: string) {
  if (step === 1) {
    const lines = [ `Read \`${epicDir}/landscape.md\`. ...` /* existing */ ];
    if (phaseInstructions) {
      lines.push("", "## Additional Context from Workflow Orchestrator", "", phaseInstructions);
    }
    return { title: "Read", instructions: lines };
  }
}
```

### 8. Web UI: Inline ActivityFeed with Orchestrator Session

The workflow orchestrator session appears as a **seamless continuation** of the
completed phase's activity in the same feed. No mode switch occurs — the three-
column workspace (status sidebar, activity feed, artifacts panel) remains active
throughout. This design reflects that watching the orchestrator evaluate
artifacts and build its recommendation is itself informative: its tool calls
scanning `landscape.md` or `brief.md` build visible trust in the proposal that
follows.

The ActivityFeed is structured in four zones when the orchestrator is active:

```
┌─────────────────────────────────────────┐
│  [frozen phase activity — dimmed]       │  phase's final tool calls / thinking
│  thinking  4s                           │
│  read  landscape.md                     │
│  ...                                    │
├── ─── Evaluating workflow... ───────────┤  separator (rendered when frozenLogs set)
│  [live orchestrator activity]           │  orchestrator's streaming tool calls
│  thinking  ...                          │
│  read  workflow-status.md               │
│  ...                                    │
├─────────────────────────────────────────┤
│  [WorkflowChat thread]                  │  multi-turn conversation
│  ● requirements are fully aligned...   │  orchestrator turn (status + options)
│  ○ focus on auth requirements           │  user turn
│  ● understood — here's my updated...   │  orchestrator turn
│                                         │
│  [text input]  [Continue →]             │
└─────────────────────────────────────────┘
```

#### Frozen logs: preserving phase activity

`trackSubagent()` replaces `lastLogs` with each new subagent's polling output.
Without intervention, the orchestrator's activity would overwrite the completed
phase's logs. To prevent this, the driver calls `webServer.freezeLogs()` before
spawning the orchestrator. This method snapshots `lastLogs` into a separate
`frozenLogs` buffer and pushes a `frozen-logs` SSE event to all clients.

The server holds both buffers independently. `frozenLogs` is included in
`replayState()` so reconnecting browsers see the complete picture. It is cleared
when the next phase begins (`pushPhase()` with a non-orchestrator phase).

**`WebServerHandle`** gains two new methods:

```typescript
/** Snapshot current lastLogs into frozenLogs and push 'frozen-logs' SSE event.
 *  Called by the driver before spawning the workflow orchestrator so that
 *  trackSubagent()'s log replacement does not erase the phase's activity. */
freezeLogs(): void;
requestWorkflowDecision(payload: WorkflowDecisionPayload, signal: AbortSignal): Promise<WorkflowDecisionFeedback>;
```

**`server-types.ts`** gains three new event/response types:

```typescript
export interface FrozenLogsEvent {
  lines: LogLine[];
}

/** SSE event payload pushed to clients when the orchestrator calls
 *  koan_propose_workflow. Matches the subset of WorkflowDecisionPayload
 *  the client needs for rendering. */
export interface WorkflowDecisionEvent {
  requestId: string;
  statusReport: string;
  recommendedPhases: WorkflowPhaseOption[];
  completedPhase: string;
}

/** Response from the POST /api/workflow-decision endpoint.
 *  Parallel to ArtifactReviewFeedback. */
export interface WorkflowDecisionFeedback {
  feedback: string;
}
```

**Server implementation** (inside `startWebServer`):

```typescript
let frozenLogs: LogLine[] = [];

// In replayState():
if (frozenLogs.length > 0) write("frozen-logs", { lines: frozenLogs });

// On the handle:
freezeLogs(): void {
  // Shallow copy to decouple from any future mutation of lastLogs.
  // Cost is negligible: bounded to 50 entries by readRecentLogs().
  frozenLogs = [...lastLogs];
  pushEvent("frozen-logs", { lines: frozenLogs });
},

// In pushPhase(): clear frozenLogs when a real phase (not orchestrator) begins.
// The orchestrator does not push a phase event, so frozenLogs persist across
// the entire orchestrator session and are only cleared when the next phase starts.
pushPhase(phase: EpicPhase): void {
  frozenLogs = [];
  // ... existing phase push logic
},
```

#### PillStrip: phase progress display

The PillStrip displays all eight active phases (excluding the `completed`
terminal marker, which is indicated by all pills turning done):

```jsx
const PHASES = [
  { id: "intake", label: "intake" },
  { id: "brief-generation", label: "brief" },
  { id: "core-flows", label: "core flows" },
  { id: "tech-plan", label: "tech plan" },
  { id: "ticket-breakdown", label: "tickets" },
  { id: "cross-artifact-validation", label: "validation" },
  { id: "execution", label: "execute" },
  { id: "implementation-validation", label: "verify" },
];

const PHASE_ORDER = [
  "intake",
  "brief-generation",
  "core-flows",
  "tech-plan",
  "ticket-breakdown",
  "cross-artifact-validation",
  "execution",
  "implementation-validation",
  "completed",
];
```

#### StatusSidebar: phase-specific status

The `PhaseStatus` dispatcher handles implemented phases with dedicated
components and falls through to `GenericStatus` for stub phases:

```jsx
function PhaseStatus({ phase, intakeProgress, stories }) {
  if (phase === "intake") {
    return intakeProgress ? (
      <IntakeStatus progress={intakeProgress} />
    ) : (
      <GenericStatus phase={phase} />
    );
  }
  switch (phase) {
    case "brief-generation":
      return <BriefStatus />;
    default:
      // Stub phases and any future phases without a dedicated widget
      return <GenericStatus phase={phase} />;
  }
}
```

#### Store: `frozenLogs` and `workflowChat`

The store gains two new slices alongside the existing `logs`:

```javascript
frozenLogs: [],     // LogLine[] — frozen snapshot of the completed phase's activity
workflowChat: [],   // WorkflowChatTurn[] — multi-turn conversation history
```

A `WorkflowChatTurn` is either an orchestrator proposal or a user response:

```typescript
type WorkflowChatTurn =
  | {
      role: "orchestrator";
      requestId: string;
      statusReport: string;
      recommendedPhases: WorkflowPhaseOption[];
    }
  | { role: "user"; text: string; pending?: boolean; failed?: boolean };
```

`pending` is set during optimistic append (cleared on fetch success).
`failed` is set when the POST to `/api/workflow-decision` fails, enabling
a retry UI. Without error handling, a fetch failure causes
`pollIpcUntilResponse()` to block indefinitely.

**Handlers:**

```javascript
export function handleFrozenLogsEvent(d) {
  set({ frozenLogs: d.lines });
}

// Each new workflow-decision event appends an orchestrator turn.
// Independent of any existing turn — multi-turn is handled by accumulation,
// not replacement.
//
// NOTE: workflow-decision does NOT set pendingInput. Setting it would toggle
// isInteractive=true, switching to PhaseContent and hiding the ActivityFeed
// where the WorkflowChat lives. This is intentional and unlike all other
// interaction types (ask, review, artifact-review, model-config).
export function handleWorkflowDecisionEvent(d) {
  set((s) => ({
    workflowChat: [
      ...s.workflowChat,
      {
        role: "orchestrator",
        requestId: d.requestId,
        statusReport: d.statusReport,
        recommendedPhases: d.recommendedPhases,
      },
    ],
  }));
}

export function handleWorkflowDecisionCancelledEvent(d) {
  // Remove the pending orchestrator turn by requestId
  set((s) => ({
    workflowChat: s.workflowChat.filter(
      (t) => !(t.role === "orchestrator" && t.requestId === d.requestId),
    ),
  }));
}
```

**`workflowChat` and `frozenLogs` are cleared on phase transition and pipeline end:**

```javascript
export function handlePhaseEvent(d) {
  set({
    phase: d.phase,
    frozenLogs: [], // phase's frozen activity no longer needed
    workflowChat: [], // conversation belongs to the previous transition
    ...(d.phase !== "intake" && { pendingInput: null, intakeProgress: null }),
  });
}

export function handlePipelineEndEvent(d) {
  set((s) => ({
    phase: d.success ? "completed" : s.phase,
    pipelineEnd: d,
    intakeProgress: null,
    frozenLogs: [],
    workflowChat: [],
  }));
}
```

#### Server: `requestWorkflowDecision()` and SSE replay

`workflowDecision` is stored in `pendingInputs` with `type: "workflow-decision"`
— identical to how `artifact-review` is stored. This is essential for **SSE
replay**: `replayState()` iterates `pendingInputs` to replay all pending
interactions for reconnecting browsers. Each `requestWorkflowDecision()` call
is independent; the client accumulates turns from successive `workflow-decision`
SSE events.

`replayState()` gains one branch:

```typescript
} else if (entry.type === "workflow-decision") {
  write("workflow-decision", { requestId, ...entry.payload });
}
```

On reconnect the client receives the full conversation history via `frozen-logs`
(replayed from `frozenLogs` buffer) and then the currently-pending
`workflow-decision` event, which it appends to `workflowChat`.

#### App.jsx changes

`workflowChat` and `frozenLogs` are **absent from `isInteractive`** — the
three-column workspace stays active. `token` is passed to `ActivityFeed`:

```jsx
const isInteractive =
  !phase || pending || showSettings || phase === "completed";
// workflowChat / frozenLogs do not affect isInteractive

{
  isInteractive ? (
    <div class="phase-content">
      <PhaseContent token={token} topic={topic} />
    </div>
  ) : (
    <ActivityFeed token={token} />
  );
}
```

#### ActivityFeed.jsx

`ActivityFeed` accepts `token` and renders all four zones. The separator and
`WorkflowChat` appear only when `frozenLogs` is non-empty (i.e., an orchestrator
session is active):

```jsx
export function ActivityFeed({ token }) {
  const logs = useStore((s) => s.logs);
  const frozenLogs = useStore((s) => s.frozenLogs);
  const workflowChat = useStore((s) => s.workflowChat);
  const streamingText = useStore((s) => s.streamingText);
  // ... scroll/flash logic unchanged ...

  const hasOrchestratorSession = frozenLogs.length > 0;

  return (
    <div class="activity-feed-scroll" ref={containerRef} onScroll={onScroll}>
      <div class="activity-feed-inner">
        {/* Zone 1: frozen phase activity */}
        {hasOrchestratorSession &&
          frozenLogs.map((line, i) =>
            renderLine(line, false, false, `frozen-${i}`, true /* dimmed */),
          )}

        {/* Zone 2: orchestrator session separator */}
        {hasOrchestratorSession && (
          <div class="workflow-separator">
            <span class="workflow-separator-label">Evaluating workflow...</span>
          </div>
        )}

        {/* Zone 3: live orchestrator tool calls */}
        {logs.map((line, i) => {
          const isInFlight = !!line.inFlight && i === logs.length - 1;
          const isFlashing = i === flashIndex;
          return renderLine(line, isInFlight, isFlashing, `live-${i}`, false);
        })}

        {/* Zone 4: WorkflowChat thread */}
        {workflowChat.length > 0 && (
          <WorkflowChat turns={workflowChat} token={token} />
        )}
      </div>
    </div>
  );
}
```

#### WorkflowChat component

`WorkflowChat` renders the full conversation thread and a text input for the
next user response. It only shows the input when the last turn is an
orchestrator proposal (i.e., awaiting user response). Once the user submits,
their turn is appended immediately client-side while the orchestrator processes
the response; when the next `workflow-decision` SSE event arrives it is appended
as the next orchestrator turn.

```jsx
function WorkflowChat({ turns, token }) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const lastTurn = turns[turns.length - 1];
  const awaitingUser = lastTurn?.role === "orchestrator";

  function selectPhase(phase) {
    // Pre-fill rather than auto-submit. Lets the user add context before
    // sending: "Proceed with core-flows, but focus on auth requirements"
    setInput(`Proceed with ${phase.label}`);
  }

  async function submit() {
    if (submitting || !input.trim() || !awaitingUser) return;
    setSubmitting(true);

    // Append user turn immediately for responsive feedback. The store will
    // receive the next orchestrator turn from SSE when it arrives.
    // Mark the turn as pending so the UI can show a sending indicator.
    const userText = input.trim();
    useStore.setState((s) => ({
      workflowChat: [
        ...s.workflowChat,
        { role: "user", text: userText, pending: true },
      ],
    }));
    setInput("");

    try {
      await fetch("/api/workflow-decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          requestId: lastTurn.requestId,
          feedback: userText,
        }),
      });
      // Mark the user turn as delivered.
      useStore.setState((s) => ({
        workflowChat: s.workflowChat.map((t) =>
          t.role === "user" && t.pending ? { ...t, pending: false } : t,
        ),
      }));
    } catch (err) {
      // Mark turn as failed so user can retry. Without this, the pipeline
      // hangs at pollIpcUntilResponse() indefinitely.
      useStore.setState((s) => ({
        workflowChat: s.workflowChat.map((t) =>
          t.role === "user" && t.pending
            ? { ...t, pending: false, failed: true }
            : t,
        ),
      }));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div class="workflow-chat">
      {turns.map((turn, i) =>
        turn.role === "orchestrator" ? (
          <OrchestratorTurn
            key={i}
            turn={turn}
            onSelect={selectPhase}
            isLatest={i === turns.length - 1}
          />
        ) : (
          <UserTurn
            key={i}
            turn={turn}
            onRetry={(text) => {
              setInput(text);
            }}
          />
        ),
      )}

      {awaitingUser && (
        <div class="workflow-chat-input">
          <textarea
            class="workflow-feedback"
            placeholder="Type instructions or feedback, or click an option above..."
            value={input}
            onInput={(e) => setInput(e.target.value)}
            disabled={submitting}
          />
          <div class="form-actions">
            <button
              class="btn btn-primary"
              onClick={submit}
              disabled={submitting || !input.trim()}
            >
              Continue →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function OrchestratorTurn({ turn, onSelect, isLatest }) {
  return (
    <div class="workflow-turn workflow-turn-orchestrator">
      <div class="workflow-turn-header">
        <span class="workflow-turn-role">workflow orchestrator</span>
      </div>
      <div
        class="workflow-turn-body"
        dangerouslySetInnerHTML={{ __html: marked.parse(turn.statusReport) }}
      />
      {/* Only show phase options on the latest orchestrator turn */}
      {isLatest && (
        <div class="workflow-options">
          {turn.recommendedPhases.map((p) => (
            <button
              class={`workflow-option${p.recommended ? " recommended" : ""}`}
              onClick={() => onSelect(p)}
            >
              <span class="workflow-option-label">{p.label}</span>
              <span class="workflow-option-context">{p.context}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function UserTurn({ turn, onRetry }) {
  return (
    <div
      class={`workflow-turn workflow-turn-user${turn.failed ? " workflow-turn-failed" : ""}`}
    >
      <span class="workflow-turn-body">{turn.text}</span>
      {turn.pending && <span class="workflow-turn-status">Sending...</span>}
      {turn.failed && (
        <div class="workflow-turn-error">
          <span>Failed to send.</span>
          <button class="btn btn-sm" onClick={() => onRetry(turn.text)}>
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
```

### 9. `workflow-status.md` (Driver-Generated Context File)

Before spawning the workflow orchestrator, the driver writes
`{epicDir}/workflow-status.md`. The driver writes this (not an LLM) for two
reasons: (1) it has authoritative phase history — inferring it from artifact
timestamps would be unreliable; (2) the file boundary invariant requires the
LLM to receive markdown, so the driver bridges its internal JSON knowledge
into a markdown document.

**`writeWorkflowStatus()`** lives in `driver.ts` (co-located with
`runWorkflowOrchestrator` which calls it). It derives the completed phase from
the `completedPhase` argument and discovers artifacts by scanning `epicDir` for
known filenames. The `availablePhases` come from the DAG successors passed by
the caller.

```typescript
import { listArtifacts } from "../epic/artifacts.js";

/** Write {epicDir}/workflow-status.md — a markdown bridge from driver JSON
 *  state to the orchestrator LLM's context. Called before orchestrator spawn.
 *
 *  completedPhase is the single just-completed phase (not a history).
 *  The driver does not maintain a phase history array; the orchestrator
 *  infers prior phases from the artifacts present in epicDir. */
async function writeWorkflowStatus(
  epicDir: string,
  completedPhase: EpicPhase,
  availablePhases: readonly EpicPhase[],
): Promise<void> {
  // listArtifacts() already exists in epic/artifacts.ts — returns ArtifactEntry[]
  // with { path, size, modifiedAt }. path is relative to epicDir.
  const artifacts = await listArtifacts(epicDir);
  const lines = [
    "# Workflow Status",
    "",
    "## Current Position",
    "",
    `The **${completedPhase}** phase has just completed.`,
    "",
    "## Available Next Phases",
    "",
    ...availablePhases.map((p) => `- **${p}** — ${PHASE_DESCRIPTIONS[p]}`),
    "",
    "## Artifacts Available",
    "",
    ...artifacts.map((a) => `- \`${a.path}\``),
  ];
  await fs.writeFile(
    path.join(epicDir, "workflow-status.md"),
    lines.join("\n"),
    "utf8",
  );
}
```

Note: `PHASE_DESCRIPTIONS` is a `Record<EpicPhase, string>` constant co-located
with `PHASE_TRANSITIONS` in `lib/phase-dag.ts`. It maps each phase to a
one-line human-readable description (e.g., `"core-flows": "Define user journeys
with sequence diagrams"`).

**Example output** (after intake completes):

```markdown
# Workflow Status

## Current Position

The **intake** phase has just completed.

## Available Next Phases

- **brief-generation** — Distill intake context into a compact product-level epic brief
- **core-flows** — Define user journeys with sequence diagrams

## Artifacts Available

- `landscape.md` — Intake findings and codebase analysis
```

### 10. Permissions

```typescript
["workflow-orchestrator", new Set([
  "koan_complete_step",
  "koan_propose_workflow",
  "koan_set_next_phase",
  // No koan_ask_question — koan_propose_workflow handles user interaction
  // No koan_request_scouts — orchestrator reads existing artifacts only
  // No write/edit — orchestrator routes, it does not produce artifacts
])],
```

`"workflow-orchestrator"` is added to `PLANNING_ROLES` so any future write
tools are automatically path-scoped to the epic directory.

---

## Codebase Touchpoints

The phase registry change (`EpicPhase` update) requires updates across the
codebase. All sites that reference old phase identifiers must be updated to use
the canonical identifiers. The following is an exhaustive list based on
codebase analysis.

### Phase identifier sites (old → new)

| File                                              | Line(s)                         | Old identifier                                                                     | New identifier                                  | Notes                                                    |
| ------------------------------------------------- | ------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------- |
| `src/planner/types.ts`                            | 55                              | `"intake" \| "brief" \| "decomposition" \| "review" \| "executing" \| "completed"` | Full 8-phase union + `"completed"`              | Core type definition                                     |
| `src/planner/driver.ts`                           | 337–426                         | Linear `intake → brief → decomposition → review → executing → completed` pipeline  | DAG-driven loop with stub handling              | Full `runPipeline()` rewrite                             |
| `src/planner/driver.ts`                           | 124                             | `role: "intake" \| "brief-writer" \| "decomposer"`                                 | Phase-to-role mapping via `PHASE_ROLE`          | `runSimplePhase` type                                    |
| `src/planner/epic/types.ts`                       | 53                              | `phase: "intake"` in `createInitialEpicState`                                      | No change (intake stays)                        | —                                                        |
| `src/planner/web/js/components/PillStrip.jsx`     | 3–11                            | `PHASES` array with `decomposition`, `review`, `executing`                         | 8-phase array                                   | See §8                                                   |
| `src/planner/web/js/components/PillStrip.jsx`     | 13                              | `PHASE_ORDER` array                                                                | 8 phases + `completed`                          | See §8                                                   |
| `src/planner/web/js/components/StatusSidebar.jsx` | 107–112                         | `case 'brief'`, `case 'decomposition'`, `case 'executing'`                         | `case 'brief-generation'` + generic fallthrough | `DecomposeStatus` and `ExecuteStatus` components removed |
| `src/planner/web/js/components/App.jsx`           | 33                              | `phase === 'completed'`                                                            | No change (`completed` terminal marker stays)   | —                                                        |
| `src/planner/web/js/components/PhaseContent.jsx`  | 21                              | `phase === 'completed'`                                                            | No change                                       | —                                                        |
| `src/planner/web/js/store.js`                     | 82                              | `phase: d.success ? 'completed' : s.phase`                                         | No change                                       | —                                                        |
| `src/planner/web/js/components/ModelConfig.jsx`   | ~line with "task decomposition" | Old terminology in model tier description                                          | Update to "task planning"                       | Cosmetic                                                 |

### Old driver code to remove

The following code in `driver.ts` is replaced by the DAG-driven loop:

- **Lines 353–354**: `phase: "decomposition"` / `pushPhase("decomposition")`
- **Lines 356–369**: Decomposer invocation, story discovery, `ensureStoryDirectory`
- **Lines 370–371**: `phase: "review"` / `pushPhase("review")`
- **Lines 373–415**: Spec review gate (`webServer.requestReview()`, review story loading, skip handling)
- **Lines 418–419**: `phase: "executing"` / `pushPhase("executing")`
- **Lines 420–426**: Story loop invocation, `phase: "completed"`

**Note:** The story loop infrastructure (`runStoryLoop`, `runStoryExecution`,
`runStoryReexecution`, `routeFromState`) and associated subagent roles
(orchestrator, planner, executor) remain in the codebase. They are not invoked
by the pipeline but will be used when the `execution` phase is implemented.
Similarly, the decomposer phase class (`phases/decomposer/`) remains for future
use by the `ticket-breakdown` phase. No phase classes are deleted.

### Spec review gate: full deletion

The spec review gate was development scaffolding. All associated code is
deleted (not retained as dormant code):

| File                                     | Code to delete                                                                                                                         |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `web/server-types.ts`                    | `ReviewStory`, `ReviewResult` types; `requestReview()` on `WebServerHandle`                                                            |
| `web/server.ts`                          | `requestReview()` implementation; `POST /api/review` endpoint; `"review"` branch in `replayState()`; review entries in `pendingInputs` |
| `web/js/store.js`                        | Review-related state and handlers                                                                                                      |
| `web/js/sse.js`                          | `"review"` and `"review-cancelled"` event routing                                                                                      |
| `web/js/components/forms/ReviewForm.jsx` | Entire file                                                                                                                            |
| `web/js/components/PhaseContent.jsx`     | Review rendering branch                                                                                                                |
| `web/css/components.css`                 | `.review-*` styles                                                                                                                     |

A future `cross-artifact-validation` phase will use a different mechanism
(likely artifact-review IPC, not the batch review UI).

### Documentation updates

| File                   | Section                        | Change                                                                                                                                      |
| ---------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `AGENTS.md`            | Pipeline phases line           | `intake → brief-generation → core-flows → tech-plan → ticket-breakdown → cross-artifact-validation → execution → implementation-validation` |
| `docs/state.md`        | Epic phases table              | Replace 6-phase table with 8-phase table                                                                                                    |
| `docs/state.md`        | `EpicPhase` comment            | Update type union in code block                                                                                                             |
| `docs/state.md`        | Spec review gate section       | Note: moved to `execution` phase (future)                                                                                                   |
| `docs/state.md`        | Audit projection `phase` field | Update example values                                                                                                                       |
| `docs/epic-brief.md`   | Pipeline references            | Update `intake → brief → decomposition → …` references                                                                                      |
| `docs/architecture.md` | Phase references               | Update any phase enumeration                                                                                                                |

### Not phase identifiers (no change needed)

These use the string `"completed"` or `"executing"` in non-phase contexts:

| File                                        | Context                                        | Why no change                                        |
| ------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------- |
| `src/planner/tools/ask.ts:268`              | `PollOutcome` switch case                      | IPC poll outcome, not epic phase                     |
| `src/planner/lib/ipc.ts:198,240`            | `PollOutcome` type                             | IPC poll outcome, not epic phase                     |
| `src/planner/lib/audit-events.ts:53,118`    | `outcome: "completed"`                         | Audit event outcome, not epic phase                  |
| `src/planner/lib/event-log.ts:186`          | `emitPhaseEnd("completed")`                    | Phase end outcome, not phase name                    |
| `src/planner/phases/base-phase.ts:175`      | `emitPhaseEnd("completed")`                    | Phase end outcome, not phase name                    |
| `src/planner/lib/ipc-responder.ts:227`      | `status === "completed"`                       | Scout projection status, not epic phase              |
| `src/planner/driver.ts:183,296`             | `status: "executing"`                          | `StoryStatus`, not `EpicPhase`                       |
| `src/planner/web/server-types.ts:220,239`   | `status: "running" \| "completed" \| "failed"` | Agent/pipeline status, not epic phase                |
| `src/planner/web/server.ts:196`             | `status: "running" \| "completed" \| "failed"` | Agent status, not epic phase                         |
| `src/planner/web/server.ts:273,391,719,957` | `type: "review"`                               | IPC interaction type for spec review, not phase name |
| `tests/state-machine.test.ts:152,216`       | `"executing"` in story status tests            | `StoryStatus`, not `EpicPhase`                       |

---

## Implementation Order

Batches are ordered for **compile-time correctness**: each batch compiles
without errors given all prior batches. Batches 1+2 are explicitly atomic —
Batch 1 removes `EpicPhase` values that `driver.ts` still references, so
Batch 2 must land in the same commit. Similarly, Batch 3A (server-types.ts
type declarations) is split out before Batch 3B (ipc-responder) because
`handleWorkflowDecisionRequest` calls `requestWorkflowDecision()` on
`WebServerHandle`, which must exist as a type before the handler compiles.

### Batch 1+2: Phase Registry + Driver Refactor (atomic — single commit)

**These two batches MUST land together.** Batch 1 removes `"brief"`,
`"decomposition"`, `"review"`, and `"executing"` from `EpicPhase`; Batch 2
rewrites the driver code that references them. Neither compiles alone.

1. **`lib/phase-dag.ts`** — New file. `PHASE_TRANSITIONS` with 8 phases,
   `IMPLEMENTED_PHASES`, `PHASE_DESCRIPTIONS`, `getSuccessorPhases()`,
   `isAutoAdvance()`, `isStubPhase()`, `isValidTransition()`.

2. **`types.ts`** — Replace `EpicPhase` with 8-phase union + `"completed"`.
   Rename `"brief"` → `"brief-generation"`. Remove `"decomposition"`,
   `"review"`, `"executing"`. Add `"core-flows"`, `"tech-plan"`,
   `"ticket-breakdown"`, `"cross-artifact-validation"`, `"execution"`,
   `"implementation-validation"`. Add `"workflow-orchestrator"` to
   `SubagentRole` and `ROLE_MODEL_TIER`.

3. **`lib/task.ts`** — Add `WorkflowOrchestratorTask` interface and add it to
   the `SubagentTask` discriminated union. Add optional
   `phaseInstructions?: string` to `SubagentTaskBase`.

4. **`lib/permissions.ts`** — Add `"workflow-orchestrator"` role entry.

5. **`epic/types.ts`** — Add `WorkflowDecisionState` interface.

6. **`driver.ts`** — Replace linear `runPipeline()` with DAG-driven loop.
   Add `PHASE_ROLE` mapping. Add `isStubPhase()` handling for stubs.
   Add `writeWorkflowStatus()`. Add `runWorkflowOrchestrator()`.
   Remove decomposer invocation, story discovery, spec review gate, and
   story loop from the main pipeline path. Keep `runStoryLoop()`,
   `runStoryExecution()`, `runStoryReexecution()`, `routeFromState()` as
   dormant code for future `execution` phase use. Add headless guard for
   multi-successor DAGs. `runSimplePhase()` gains `phaseInstructions?`.
   `runPhase()` returns `boolean` for per-phase error checking.

7. **`epic/state.ts`** — Add `readWorkflowDecision(subagentDir)` helper.

8. **`web/js/components/PillStrip.jsx`** — Replace `PHASES` and `PHASE_ORDER`
   with 8-phase arrays using new identifiers. (Must land with EpicPhase rename.)

9. **`web/js/components/StatusSidebar.jsx`** — Update `PhaseStatus` switch:
   rename `'brief'` → `'brief-generation'`, remove `'decomposition'` and
   `'executing'` cases, remove `DecomposeStatus` and `ExecuteStatus` components.
   Remove `phase === 'review'` branch from `GenericStatus`.
   Stub phases fall through to `GenericStatus`.

10. **`web/js/components/PhaseContent.jsx`** — Remove review rendering branch
    (part of spec review gate deletion).

### Batch 3A: Server Types (pure type declarations — no behavior)

These are type-only additions that must exist before Batch 3B's
`ipc-responder.ts` changes can compile.

11. **`web/server-types.ts`** — Add `FrozenLogsEvent`, `WorkflowDecisionEvent`,
    `WorkflowDecisionFeedback`; add `freezeLogs()` and `requestWorkflowDecision`
    to `WebServerHandle`. Add `"workflow-decision"` to `PendingEntry.type` union.

### Batch 3B: IPC + Tools

12. **`lib/ipc.ts`** — Add `WorkflowDecisionIpcFile` with `WorkflowDecisionResponse`
    carrying `id`, `respondedAt`, `feedback` (matching `ArtifactReviewResponse`
    convention). Add factory helper. Update `IpcFile` union. Add
    `"workflow-decision"` branch to `pollIpcUntilResponse` — required: without
    it, `koan_propose_workflow` polls forever and the pipeline hangs.

13. **`tools/workflow-decision.ts`** — New file. `koan_propose_workflow`
    (IPC write + poll + return text) and `koan_set_next_phase` (reads
    `task.json` via `readTaskFile(ctx.subagentDir)`, narrows to
    `WorkflowOrchestratorTask` via `task.role === "workflow-orchestrator"`,
    validates, writes `workflow-decision.json` to subagentDir).

14. **`lib/ipc-responder.ts`** — Add `handleWorkflowDecisionRequest`. Add
    dispatch case in `runIpcResponder`'s if-chain.

15. **`extensions/koan.ts`** — Register the two new tools.

### Batch 4: Phase Class

16. **`phases/workflow-orchestrator/phase.ts`** — `WorkflowOrchestratorPhase`
    with 2-step structure and `validateStepCompletion` gate (enforces both
    `proposalMade` and `nextPhaseSet`). Use `event.isError`
    (matching `ReviewablePhase` convention, not `event.error`).

17. **`phases/workflow-orchestrator/prompts.ts`** — System prompt and step
    guidance (`availablePhases` injected in step 2 from task manifest).

18. **`phases/dispatch.ts`** — Add `"workflow-orchestrator"` case. The case
    reads `task as WorkflowOrchestratorTask` and passes
    `{ completedPhase: task.completedPhase, availablePhases: task.availablePhases }`
    as the config argument to the `WorkflowOrchestratorPhase` constructor.

### Batch 5: Web Server + UI

19. **`web/server.ts`** — Add `frozenLogs` buffer. `freezeLogs()` snapshots
    `[...lastLogs]` → `frozenLogs` and pushes `"frozen-logs"` SSE event. Add
    `"frozen-logs"` branch in `replayState()`. `requestWorkflowDecision()` stores
    in `pendingInputs` with `type: "workflow-decision"` (required for SSE replay).
    Add POST `/api/workflow-decision`. Add `"workflow-decision"` branch in
    `replayState()`. Push `"workflow-decision-cancelled"` SSE event on abort.
    Clear `frozenLogs` in `pushPhase()`. Call `webServer.freezeLogs()` before
    spawning orchestrator (driven from driver via the handle).

20. **`web/js/store.js`** — Add `frozenLogs: []` and `workflowChat: []` slices.
    Add `handleFrozenLogsEvent`, `handleWorkflowDecisionEvent`,
    `handleWorkflowDecisionCancelledEvent`. Update `handlePhaseEvent` to clear
    both. Update `handlePipelineEndEvent` to clear both.

21. **`web/js/sse.js`** — Add routing for `'frozen-logs'`, `'workflow-decision'`,
    `'workflow-decision-cancelled'`.

22. **`web/js/components/App.jsx`** — Pass `token` prop to `ActivityFeed`.
    Confirm `workflowChat` and `frozenLogs` are absent from `isInteractive`.
    Add comment explaining the intentional asymmetry: workflow-decision is the
    only interaction type that does NOT set `pendingInput`.

23. **`web/js/components/ActivityFeed.jsx`** — Accept `token` prop. Render four
    zones: frozen logs (dimmed), orchestrator separator, live logs, `WorkflowChat`.
    Separator and `WorkflowChat` appear only when `frozenLogs.length > 0`.

24. **`web/css/components.css`** — Styles for: `.activity-line-frozen` (dimmed
    opacity), `.workflow-separator` (centered divider line + label), `.workflow-chat`,
    `.workflow-turn`, `.workflow-turn-orchestrator`, `.workflow-turn-user`,
    `.workflow-turn-failed` (error indicator), `.workflow-turn-status` (sending
    indicator), `.workflow-turn-error` (retry button container),
    `.workflow-options`, `.workflow-option`, `.workflow-feedback`.

### Batch 6: Phase guidance threading

25. **`lib/runtime-context.ts`** — Add `phaseInstructions?: string` to
    `RuntimeContext` interface.

26. **`extensions/koan.ts`** — In `before_agent_start`, after `readTaskFile`,
    set `ctx.phaseInstructions = task.phaseInstructions`.

27. **Phase guidance functions** — Add `phaseInstructions` parameter to step 1
    guidance functions in: `phases/intake/phase.ts` (pass `this.ctx.phaseInstructions`
    to `intakeStepGuidance`), `phases/brief-writer/phase.ts` (pass to
    `briefWriterStepGuidance`), and the corresponding `prompts.ts` files.
    (Remaining phase guidance functions will be added when their phases are
    implemented.)

### Batch 7: Documentation

28. **`AGENTS.md`** — Update pipeline phases line to 8-phase sequence.

29. **`docs/state.md`** — Replace phase table and `EpicPhase` code blocks.
    Update spec review gate section. Update audit projection examples.

30. **`docs/epic-brief.md`** — Update pipeline references (`intake →
brief-generation → …`).

31. **`docs/architecture.md`** — Update pipeline description, add workflow
    orchestrator section.

### Batch 8: Tests

32. **`tests/state-machine.test.ts`** — Update any tests that reference
    `EpicPhase` values. Note: tests referencing `StoryStatus` `"executing"` are
    unaffected (story status is separate from epic phase).

33. **Phase DAG tests** — New test file for `lib/phase-dag.ts`: test
    `getSuccessorPhases`, `isAutoAdvance`, `isStubPhase`, `isValidTransition`
    with both single-successor and multi-successor configurations.

---

## Invariant Compliance

| Invariant                       | How this design complies                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. File boundary**            | Orchestrator reads markdown (`workflow-status.md`, artifacts). `koan_set_next_phase` bridges both: receives LLM input, writes `workflow-decision.json` to subagentDir for the driver to read after exit.                                                                                                                                                                                |
| **2. Step-first workflow**      | `WorkflowOrchestratorPhase` follows the identical boot-prompt pattern. Boot prompt: one sentence. Step guidance arrives via the first `koan_complete_step` return value.                                                                                                                                                                                                                |
| **3. Driver determinism**       | Driver reads `workflow-decision.json` for the next phase. DAG validation is a pure function. Stub detection is a set lookup. The driver never parses orchestrator text output.                                                                                                                                                                                                          |
| **4. Default-deny permissions** | `"workflow-orchestrator"` has its own `ROLE_PERMISSIONS` entry with only three tools. Unknown roles are blocked.                                                                                                                                                                                                                                                                        |
| **5. Need-to-know prompts**     | Boot prompt is one sentence. Available phases arrive via step 2 guidance (from `task.json`). Phase history arrives via `workflow-status.md` in step 1.                                                                                                                                                                                                                                  |
| **6. Directory-as-contract**    | `task.json` carries `completedPhase` and `availablePhases`. IPC uses `ipc.json`. Decision persisted in `workflow-decision.json` — all three files live in the subagent directory. `koan_set_next_phase` reads `availablePhases` from `task.json` and writes the decision to the same directory. The driver reads the decision from the subagent directory after the orchestrator exits. |

---

## Risks and Mitigations

| Risk                                                                                              | Mitigation                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Orchestrator exits without calling `koan_set_next_phase`                                          | `validateStepCompletion(2)` blocks `koan_complete_step` unless both `proposalMade` and `nextPhaseSet` are true. If process crashes (non-zero exit), `runWorkflowOrchestrator()` returns `null` and the driver returns `{ success: false }`.                                                                                              |
| Orchestrator skips user interaction (calls `koan_set_next_phase` without `koan_propose_workflow`) | `validateStepCompletion(2)` checks `proposalMade` flag — set only on successful `koan_propose_workflow` call. Gate returns error message directing the LLM to call `koan_propose_workflow` first.                                                                                                                                        |
| `WorkflowChat.submit()` fetch failure leaves pipeline hanging                                     | `submit()` wraps fetch in try/catch. On failure, the user turn is marked `failed: true` and a retry UI is shown. Without this, `pollIpcUntilResponse()` blocks indefinitely.                                                                                                                                                             |
| User provides ambiguous feedback cycling indefinitely                                             | `koan_propose_workflow` may be called multiple times; loop terminates only at `koan_set_next_phase`. Same pattern as `koan_review_artifact`, which has not required a loop guard in practice.                                                                                                                                            |
| Token cost on single-successor DAGs                                                               | `isAutoAdvance()` short-circuits before any orchestrator spawn. Zero cost for deterministic transitions.                                                                                                                                                                                                                                 |
| Token cost on stub phases                                                                         | `isStubPhase()` short-circuits before any subagent spawn. Stubs are a log line and a state write — no LLM cost.                                                                                                                                                                                                                          |
| `pollIpcUntilResponse` missing `workflow-decision` branch                                         | Addressed explicitly in Batch 3B item 12. Without it, `koan_propose_workflow` polls forever — pipeline hangs indefinitely on every multi-successor transition.                                                                                                                                                                           |
| Headless mode (no webServer) with multi-successor DAG                                             | `runPipeline()` guards: when `webServer` is null and `successors.length > 1`, auto-advance to `successors[0]` with log warning. Without the web server the IPC responder does not run and `koan_propose_workflow` would poll forever.                                                                                                    |
| `frozenLogs` growing large for long-running phases                                                | `frozenLogs` is a snapshot of `lastLogs`, which is bounded by `readRecentLogs(dir, 50)` in `trackSubagent()`. Maximum 50 entries regardless of phase duration.                                                                                                                                                                           |
| `workflowChat` state desync on browser reconnect                                                  | `replayState()` replays the pending `workflow-decision` event; client appends it to `workflowChat` as a fresh orchestrator turn. Prior turns (already-responded) are not replayed — they are gone on reconnect. This is acceptable: the user can read the active proposal and the thread restores from the current pending turn forward. |
| User submits while orchestrator is still processing previous response                             | The `WorkflowChat` input is only active when `lastTurn.role === 'orchestrator'`. Once the user submits, the turn appends and the input is hidden until the next `workflow-decision` SSE event arrives.                                                                                                                                   |
| Stale `workflowChat` or `frozenLogs` persists after cancellation                                  | `handlePhaseEvent` and `handlePipelineEndEvent` clear both slices. Server-side cancel rejects `pendingInputs` entries, pushing `"workflow-decision-cancelled"` → client removes the pending orchestrator turn from `workflowChat`.                                                                                                       |
| SSE replay loses active workflow decision on browser reconnect                                    | `requestWorkflowDecision()` stores in `pendingInputs` (same as `artifact-review`). `replayState()` includes a `"workflow-decision"` branch. On reconnect, browser receives the payload and appends an orchestrator turn.                                                                                                                 |
| `workflow-decision.json` survives a crashed run                                                   | The subagent directory label includes a timestamp (`workflow-orch-${completedPhase}-${Date.now()}`), ensuring each invocation gets a fresh directory. No stale decision file from a previous run is ever read.                                                                                                                           |
| `koan_set_next_phase` proposes a phase not in `availablePhases`                                   | Tool validates against `availablePhases` from `task.json`. `isValidTransition()` provides a second guard at the driver level after the orchestrator exits.                                                                                                                                                                               |
| Future phase additions introduce invalid transitions                                              | `isValidTransition()` validates at the tool level. TypeScript exhaustive checking on `EpicPhase` catches missing DAG entries at compile time. The DAG constant handles transition edges; the Phase Promotion Checklist (§Phase Transition DAG) enumerates all other files that need updating when promoting a stub.                      |
| Dormant story loop code drifts from the codebase                                                  | Story loop code (`runStoryLoop`, `runStoryExecution`, etc.) is retained but unreachable from the main pipeline. When the `execution` phase is implemented, these functions will be the starting point. Keeping them avoids re-implementing proven infrastructure.                                                                        |
