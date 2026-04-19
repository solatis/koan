# Core Flows Phase

Insert a core-flows phase between the epic brief and decomposition, producing
a product-level interaction specification (`flows.md`) that anchors all
downstream work in explicit user journeys.

---

## Design Decisions

### Product decisions must precede scope decisions

The brief captures the **problem**. The decomposer defines the **units of
work**. Between these sits an unaddressed question: what does the user
actually _experience_? Without an explicit answer, the decomposer invents
interaction patterns implicitly — embedding UX assumptions inside story scope
descriptions where they cannot be reviewed, challenged, or referenced.

The core-flows phase forces these product decisions to happen explicitly,
with human alignment, before any scope decomposition begins. This prevents a
category of downstream error where stories implement a technically correct
solution to the wrong interaction model.

### Flows describe interactions between actors and systems, not just UI

A flow is a complete interaction path — from trigger to exit — between actors
(users, operators, services, CLIs) and systems. For a web application, flows
describe screen navigation and feedback. For a backend service, flows describe
API request/response paths. For infrastructure work, flows describe operational
procedures. For a refactoring epic, flows describe the behavioral contracts
that must be preserved.

The flows-writer adapts its output to the domain described in the brief. The
artifact structure is the same regardless of domain: trigger, step-by-step
actions/responses, exit condition.

This generalization matters because the artifact cascade depends on every
downstream phase being able to reference `flows.md` unconditionally. A
skippable phase creates conditional logic in every consumer ("if flows.md
exists, read it; otherwise, infer from brief.md"). A mandatory phase that
adapts to the domain avoids this.

### Codebase grounding before design prevents specification drift

The flows-writer reads the codebase (via scouts) before designing flows. This
is not optional — it is what prevents the specification from diverging from
reality. An LLM designing flows from the brief alone will propose interaction
patterns that don't match the existing system's structure, navigation model,
or data availability.

By scouting first, the flows-writer grounds its design in what actually exists:
current screen layouts, API endpoints, CLI commands, data models. New flows
extend or modify the existing interaction surface rather than inventing one
from scratch.

### User alignment happens through questions and artifact review

The flows-writer uses two complementary alignment mechanisms:

- **`koan_ask_question`** during the Align step — targeted questions about
  interaction design decisions before any artifact is drafted. This surfaces
  ambiguities while the design is still malleable.
- **`koan_review_artifact`** during the Draft & Review step — presentation of
  the complete spec for holistic review. This catches issues that individual
  questions miss (e.g., flows that contradict each other, missing edge cases,
  information hierarchy problems).

The two mechanisms serve different cognitive purposes. Questions resolve
specific uncertainties. Artifact review validates the whole. Neither alone
is sufficient.

### Four dimensions of interaction design

When thinking through flows, the flows-writer considers four dimensions that
surface the decisions users care about:

1. **Information hierarchy** — what information is critical vs. secondary.
   This determines what users see first, what is progressively disclosed,
   and how information is grouped.

2. **User journey integration** — where this flow starts, where it exits,
   how it connects to adjacent workflows. No flow exists in isolation.

3. **Placement & affordances** — how actions are accessed, how they behave,
   how discoverable they are within the existing interaction surface.

4. **Feedback & state communication** — how users know an action is in
   progress, how success/error/edge cases are communicated.

These dimensions are not aesthetic — they are architectural. They determine
what data must be available, what state transitions must occur, and what error
paths must exist. The tech plan and implementation plans downstream will trace
back to these decisions.

### Flows are the strongest product-level reference downstream

Once accepted, `flows.md` becomes the artifact that downstream phases consult
to understand _what the user should experience_. The decomposer reads it to
scope stories that implement specific flows. The planner reads it to understand
what behavior each story must produce. The orchestrator reads it to verify that
completed work matches the intended experience.

This creates a traceable chain: every story should be traceable to one or more
flows. Every plan step should serve a flow requirement. Every verification
check should validate a flow's expected behavior.

The reference is enforced at the prompt level (downstream agents are instructed
to read `flows.md`) rather than at runtime (no mechanical blocking on flow
misalignment). This is a deliberate choice for the current pipeline: prompt-
level references are sufficient for alignment, and runtime blocking would
require a validation phase that does not yet exist.

### The artifact cascade now has four links

The pipeline's artifact chain grows from three artifacts to four:

```
landscape.md        (intake — codebase findings, decisions, constraints)
  → brief.md          (brief — problem + goals + constraints)
    → flows.md         (core-flows — interaction specifications)
      → story.md × N  (decomposition — units of work)
        → plan/ × N   (planner — implementation plans)
```

Each artifact is progressively more specific. Each phase reads all preceding
artifacts (not just the immediate predecessor). This creates redundant
reference paths — the decomposer reads both the brief and the flows, not
just the flows — which prevents telephone-game degradation where meaning
is lost in each translation step.

---

## Philosophy Captures for Documentation

The following concepts should be captured as high-level design principles in
`docs/core-flows.md`. They encode reasoning that will guide future phases
(validation gates, agentic workflow progression) even though those phases are
not implemented yet.

### Artifact as contract

Each phase in the pipeline produces a markdown artifact. That artifact is the
authoritative record of decisions made during that phase. Downstream phases
treat it as a contract — they read it, reference it, and are constrained by
it. The artifact replaces verbal agreements, implicit assumptions, and
scattered context.

When all phases are complete, the set of artifacts (landscape.md, brief.md,
flows.md, story.md, plan/) forms a complete audit trail from user intent to
implementation. Any phase's output can be reviewed in isolation to understand
what was decided and why.

### Product-before-technical ordering

The pipeline is ordered so that product decisions (what should the user
experience?) are made before technical decisions (how should the code be
structured?). This is not arbitrary sequencing — it prevents a class of
planning failures where technically elegant solutions are built for the
wrong interaction model.

The ordering is: problem statement (brief) → interaction design (flows) →
scope decomposition (stories) → technical planning (plans). Each phase
constrains the next. Reversing the order (e.g., defining architecture before
flows) would allow technical convenience to override user experience.

### Validation as a future phase category

The current pipeline validates artifacts through human review gates (the
`koan_review_artifact` mechanism). A future evolution would add automated
validation phases: an LLM agent that reads the brief, flows, and stories
together and checks for contradictions, coverage gaps, and assumption drift.

The design principles that make this possible are already in place:

- Artifacts are self-contained markdown files (no external state to query)
- Each artifact has a well-defined scope (brief = problem, flows = interactions,
  stories = units of work)
- Cross-artifact consistency can be checked by reading multiple files

When validation phases are added, they should follow the same subagent pattern:
step-first workflow, role-based permissions, artifact review for findings. The
validation agent reads artifacts, identifies issues, and presents findings
for human decision.

### Toward an agentic workflow

The current pipeline is a fixed linear sequence: every phase runs in order,
every phase is mandatory. This is the correct starting point — it ensures all
artifacts are always present and the cascade is complete.

A future evolution decomposes this into an agentic workflow where an
orchestrating agent recommends which phase to run next based on the current
state of artifacts. For example:

- After a brief is accepted, the agent might recommend core-flows for a
  feature epic but skip to decomposition for a pure refactoring epic.
- After validation finds issues, the agent might recommend revising the
  brief rather than patching the flows.
- After a requirement change, the agent might cascade updates through
  the artifact chain in the correct order.

The prerequisite for this evolution is that every phase can run independently
(given its input artifacts) and that the artifact contracts are well-defined.
The current mandatory pipeline establishes these contracts. The agentic
workflow relaxes the ordering while preserving the contracts.

---

## Changes

### 1. Flows-Writer Phase — `src/planner/phases/flows-writer/phase.ts`

**New file.** Extends `BasePhase`. Role: `"flows-writer"`. Total steps: 6.

Structural clone of `BriefWriterPhase` with the addition of the review gate
pattern. The key differences:

- More steps (6 vs 3): Read → Explore → Align → Re-explore → Draft & Review → Finalize
- More tools: adds `koan_request_scouts` and `koan_ask_question` alongside
  `koan_review_artifact`
- Same review gate on the Draft & Review step (step 5): `validateStepCompletion`
  requires at least one accepted `koan_review_artifact` call before
  `koan_complete_step` is allowed

The 6-step design follows the single-cognitive-goal principle:

| Step              | Goal                                    | Tools                       |
| ----------------- | --------------------------------------- | --------------------------- |
| 1. Read           | Comprehend brief + landscape            | (read-only)                 |
| 2. Explore        | Ground in codebase reality              | koan_request_scouts         |
| 3. Align          | Resolve design ambiguities with user    | koan_ask_question           |
| 4. Re-explore     | Follow up on gaps revealed by alignment | koan_request_scouts         |
| 5. Draft & Review | Produce and iterate on flows.md         | write, koan_review_artifact |
| 6. Finalize       | Phase complete                          | —                           |

Steps 3 and 4 are deliberately separated: the architecture Pitfalls section
documents that combining "ask questions" and "follow-up investigation" in
one step lets the LLM produce superficial questions knowing it has a scout
escape hatch, or skip follow-up investigation by calling koan_complete_step
early. Separating them means questions are asked without knowing a follow-up
scout step exists, and the follow-up step runs regardless.

**Review outcome tracking** follows the brief-writer pattern exactly:
`tool_call` listener marks `lastReviewAccepted = false` when
`koan_review_artifact` is called; `tool_result` listener checks for "ACCEPTED"
prefix and sets `true`. `validateStepCompletion(step === 5)` gates on this.

**Step-level permission gating:** Step 1 (Read) is read-only — blocked via
`STEP_1_BLOCKED_TOOLS` in `checkPermission`. The permission fence reads
`ctx.flowsWriterStep` to determine the current step. All other steps have
full role permissions.

```typescript
export class FlowsWriterPhase extends BasePhase {
  protected readonly role = "flows-writer";
  protected readonly totalSteps = 6;
  private lastReviewAccepted: boolean | null = null;

  constructor(pi, ctx, log?, eventLog?) {
    super(pi, ctx, log, eventLog);
    // Review outcome tracking (identical to BriefWriterPhase)
    pi.on("tool_call", (event) => {
      if (event.toolName === "koan_review_artifact")
        this.lastReviewAccepted = false;
      return undefined;
    });
    pi.on("tool_result", (event) => {
      if (event.toolName === "koan_review_artifact" && !event.isError) {
        const text = event.content?.[0];
        if (text && "text" in text && typeof text.text === "string")
          this.lastReviewAccepted = text.text.startsWith("ACCEPTED");
      }
    });
  }

  protected override onStepUpdated(step: number): void {
    this.ctx.flowsWriterStep = step;
  }

  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 5) {
      if (this.lastReviewAccepted === null)
        return "You must call koan_review_artifact on flows.md before completing this step.";
      if (!this.lastReviewAccepted)
        return "The user provided feedback — revise flows.md and present again.";
    }
    return null;
  }
}
```

### 2. Flows-Writer Prompts — `src/planner/phases/flows-writer/prompts.ts`

**New file.** System prompt + 6-step guidance.

**System prompt** — establishes a product designer role focused on interaction
specification:

```
You are an interaction designer for a coding task planner. You read the epic
brief and codebase context, then design the core interaction flows — complete
user journeys from trigger to exit.

## Your role

You define WHAT the user experiences. You do NOT define scope boundaries
(that belongs to the decomposer) or implementation approach (that belongs
to the planner). You describe the interactions the product should support,
grounded in what actually exists in the codebase.

## What you produce

One file: **flows.md** in the epic directory.

## Flow structure

Each flow must contain:
- **Name and short description**
- **Trigger / entry point** — what initiates this flow
- **Steps** — user/system actions and responses, numbered
- **Exit condition** — what the user sees at completion

Optional:
- Sequence diagrams (Mermaid) for multi-actor interactions
- ASCII wireframes for UI layout decisions
- Summary table at the end (Flow | Actor | Entry Point | Exit)

## Constraints

- Keep each flow under 30 lines.
- No code, no file paths, no component names.
- No technical implementation details — this is a product-level spec.
- Flows describe interactions between actors and systems — users,
  operators, services, CLIs, data pipelines. Adapt to the domain.
- If the epic is a refactoring, flows describe the behavioral contracts
  that must be preserved (what the user should continue to experience).

## Design dimensions

When designing each flow, think through:
1. **Information hierarchy** — what's critical vs. secondary
2. **User journey integration** — entry, exit, adjacent workflows
3. **Placement & affordances** — how actions are accessed and behave
4. **Feedback & state communication** — progress, success, errors, edge cases

## Review

After drafting, invoke `koan_review_artifact` to present flows.md for review.
If the user provides feedback, revise and present again. Continue until accepted.

{REVIEW_PROTOCOL}
```

**Step 1 — Read** (read-only comprehension):

```
Read the following files to understand the problem space:

- `{epicDir}/brief.md` — problem statement, goals, constraints
- `{epicDir}/landscape.md` — codebase findings, decisions, conventions

Build a thorough mental model of:
- What is being built or changed, and why
- Who the actors are (users, operators, services, external systems)
- What interaction surface already exists
- What constraints bound the design

Do NOT write files, request scouts, or ask questions in this step.
```

**Step 2 — Explore** (codebase grounding):

```
Explore the codebase to understand the current interaction surface.

Use `koan_request_scouts` to dispatch investigators that map:
- Current user-facing interfaces (UI screens, CLI commands, API endpoints)
- Existing interaction patterns (navigation model, feedback patterns, error handling)
- Data availability at each interaction point (what information is accessible where)
- Adjacent workflows that the new flows must integrate with

Ground your understanding in what actually exists. Flows designed without
codebase grounding will diverge from the system's real structure.
```

**Step 3 — Align** (interaction design alignment):

```
Think through the interaction design decisions for this epic, then
align with the user on points of ambiguity.

For each potential flow, consider the four design dimensions:
- Information hierarchy: what's critical vs. secondary?
- User journey integration: where does the user come from and go next?
- Placement & affordances: how are actions accessed?
- Feedback & state: how does the user know what's happening?

For points of ambiguity or uncertainty, use `koan_ask_question` to
align with the user. Ask about substantive decisions that shape the
experience — not nitpicky details where a reasonable default exists.

Ground questions in codebase findings: "Scout found the current
dashboard shows X — should the new flow integrate here or as a
separate view?"

Multiple rounds of questions is normal. The goal is shared understanding
before drafting, not speed.

Do NOT request scouts in this step — focus on alignment questions only.
If the user's answers reveal codebase areas you haven't investigated,
note them. The next step is specifically for follow-up exploration.
```

**Step 4 — Re-explore** (follow-up codebase investigation):

```
Based on the alignment decisions from step 3, determine whether
follow-up codebase exploration is needed.

If the user's answers revealed:
- Areas of the codebase you haven't investigated
- Integration points that need verification
- Patterns or conventions that affect flow design

Use `koan_request_scouts` to dispatch targeted investigations.

If no follow-up exploration is needed, call koan_complete_step
with a note that alignment is sufficient to proceed to drafting.

Do NOT ask the user questions in this step — that was step 3's
mandate. This step is for investigation only.
```

**Step 5 — Draft & Review** (artifact production):

```
Write `{epicDir}/flows.md` with all interaction flows.

Structure each flow as documented in your system prompt:
name, trigger, numbered steps, exit. Keep each flow under 30 lines.
No code, no file paths, no component names.

If the epic involves multiple distinct interaction paths, include a
summary table at the end:

| Flow | Actor | Entry Point | Exit |

After writing, invoke `koan_review_artifact` with the path to flows.md.

If the user responds with feedback, revise to address every point,
then invoke koan_review_artifact again.

If the user accepts, call koan_complete_step.
```

**Step 6 — Finalize**: "Phase complete."

### 3. Type Foundations — `src/planner/types.ts`

Add `"flows-writer"` to `SubagentRole`:

```typescript
export type SubagentRole =
  | "intake"
  | "scout"
  | "decomposer"
  | "brief-writer"
  | "flows-writer"
  | "orchestrator"
  | "planner"
  | "executor";
```

Add `"flows"` to `EpicPhase`:

```typescript
export type EpicPhase =
  | "intake"
  | "brief"
  | "flows"
  | "decomposition"
  | "review"
  | "executing"
  | "completed";
```

Add to `ROLE_MODEL_TIER` — use `"strong"` (interaction design requires
genuine reasoning about user experience, not mechanical transformation):

```typescript
"flows-writer": "strong",
```

### 4. Task Manifest — `src/planner/lib/task.ts`

Add `FlowsWriterTask` interface:

```typescript
export interface FlowsWriterTask extends SubagentTaskBase {
  role: "flows-writer";
}
```

Add to `SubagentTask` union:

```typescript
export type SubagentTask =
  | IntakeTask
  | ScoutTask
  | DecomposerTask
  | BriefWriterTask
  | FlowsWriterTask
  | OrchestratorTask
  | PlannerTask
  | ExecutorTask;
```

### 5. Permissions — `src/planner/lib/permissions.ts`

Add `"flows-writer"` to `ROLE_PERMISSIONS`:

```typescript
[
  "flows-writer",
  new Set([
    "koan_complete_step",
    "koan_review_artifact",
    "koan_ask_question",
    "koan_request_scouts",
    "edit",
    "write",
  ]),
],
```

This is the most tool-rich planning role. It needs:

- Scouts for codebase exploration (grounding)
- Questions for interaction design alignment
- Artifact review for the draft-revise loop
- Write/edit for producing flows.md

Add `"flows-writer"` to `PLANNING_ROLES` (path-scoped to epic directory).

Add `flowsWriterStep` as the 7th parameter to `checkPermission`:

```typescript
export function checkPermission(
  role: string,
  toolName: string,
  epicDir?: string,
  toolArgs?: Record<string, unknown>,
  intakeStep?: number,
  briefWriterStep?: number,
  flowsWriterStep?: number,    // ← new parameter
): { allowed: boolean; reason?: string } {
```

Add step 1 gating block (after the brief-writer step 1 block):

```typescript
if (
  role === "flows-writer" &&
  flowsWriterStep === 1 &&
  STEP_1_BLOCKED_TOOLS.has(toolName)
) {
  return {
    allowed: false,
    reason:
      `${toolName} is not available during the Read step (step 1). ` +
      "Complete koan_complete_step first to advance to the Explore step.",
  };
}
```

Update the `STEP_1_BLOCKED_TOOLS` comment to include flows-writer:

```typescript
// STEP_1_BLOCKED_TOOLS: tools disallowed during the intake Extract step (step 1),
// brief-writer Read step (step 1), and flows-writer Read step (step 1).
```

**Note on parameter proliferation:** The `checkPermission` function already
takes `intakeStep` and `briefWriterStep` as separate parameters. Adding
`flowsWriterStep` continues this pattern. Consider consolidating these into a
single `{ role, step }` object in a follow-up refactor, but do not block this
change on that refactor.

### 5a. Call-Site Update — `src/planner/phases/base-phase.ts`

The only call to `checkPermission` lives in `base-phase.ts`'s `tool_call`
event handler (lines 100–106). It currently passes 6 arguments. Add
`this.ctx.flowsWriterStep` as the 7th argument:

```typescript
const perm = checkPermission(
  this.role,
  event.toolName,
  this.ctx.epicDir ?? undefined,
  event.input as Record<string, unknown>,
  this.ctx.intakeStep,
  this.ctx.briefWriterStep,
  this.ctx.flowsWriterStep, // ← new argument
);
```

**Why this is critical:** Without this change, `checkPermission` receives
`undefined` for `flowsWriterStep`. The gate check
`role === "flows-writer" && undefined === 1` evaluates to `false` — the
step 1 write-block silently never fires. TypeScript does not catch this
because the parameter is optional. The architecture Pitfalls section
documents this exact failure mode: "The original 3-step intake design told
the LLM not to scout in step 1; it frontloaded all work into step 1 anyway."
The mechanical gate exists to prevent this; omitting the call-site update
renders it inoperative.

### 6. Runtime Context — `src/planner/lib/runtime-context.ts`

Add `flowsWriterStep` field to `RuntimeContext` interface:

```typescript
flowsWriterStep: number;
```

Initialize to `0` in `createRuntimeContext()`:

```typescript
flowsWriterStep: 0,
```

This mirrors the `briefWriterStep` pattern exactly: non-optional, initialized
to `0`, updated by `FlowsWriterPhase.onStepUpdated()`, read by the permission
fence in `checkPermission`. The `0` initial value is safe because the step 1
gate checks `=== 1`, so `0` does not trigger blocking.

Add a doc comment mirroring the existing `briefWriterStep` comment:

```typescript
// flowsWriterStep mirrors intakeStep/briefWriterStep for the flows-writer
// role: the permission fence uses it to block write/edit/scouts/questions
// during the read-only Read step (step 1).
```

### 7. Dispatch — `src/planner/phases/dispatch.ts`

Add `"flows-writer"` case:

```typescript
case "flows-writer": {
  const phase = new FlowsWriterPhase(pi, ctx, logger, eventLog);
  await phase.begin();
  break;
}
```

Add import:

```typescript
import { FlowsWriterPhase } from "./flows-writer/phase.js";
```

### 8. Driver — `src/planner/driver.ts`

Add `runFlowsWriter` function (parallel to `runBriefWriter`):

```typescript
async function runFlowsWriter(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
): Promise<boolean> {
  const subagentDir = await ensureSubagentDirectory(epicDir, "flows-writer");
  const opts: SpawnOptions = {
    cwd,
    extensionPath,
    log,
    webServer: webServer ?? undefined,
  };
  const result = await spawnTracked(
    "flows-writer",
    "flows-writer",
    "flows-writer",
    { role: "flows-writer", epicDir },
    subagentDir,
    undefined,
    opts,
    webServer,
  );
  if (result.exitCode !== 0) {
    log("Flows writer failed", { exitCode: result.exitCode });
    return false;
  }
  return true;
}
```

Insert between brief and decomposition in `runPipeline`:

```typescript
// After brief succeeds:
const afterBrief = await loadEpicState(epicDir);
await saveEpicState(epicDir, { ...afterBrief, phase: "flows" });
webServer?.pushPhase("flows");

const flowsOk = await runFlowsWriter(
  epicDir,
  cwd,
  extensionPath,
  log,
  webServer,
);
if (!flowsOk)
  return { success: false, summary: "Core flows generation failed" };

// Continue to decomposition:
const afterFlows = await loadEpicState(epicDir);
await saveEpicState(epicDir, { ...afterFlows, phase: "decomposition" });
webServer?.pushPhase("decomposition");
```

### 9. Downstream Prompt Updates

**`src/planner/phases/decomposer/prompts.ts`** — Step 1 (Analysis):

Add `flows.md` to the files-to-read list:

```typescript
`- \`${epicDir}/flows.md\` — core interaction flows: triggers, user actions, exit conditions`,
```

Add to "What to understand":

```
- What interaction flows has the user approved? Stories must implement
  these flows — do not invent interaction patterns not present in flows.md.
```

Add to system prompt strict rules:

```
- MUST NOT invent interaction patterns not present in flows.md.
- SHOULD trace each story to one or more flows it implements.
```

**`src/planner/phases/planner/prompts.ts`** — Step 1 (Analysis):

Add after the brief.md reading instruction:

```typescript
`4. Read \`${epicDir}/flows.md\` — understand the interaction flows this story ` +
`implements. The plan must produce the behavior described in these flows.`,
```

**`src/planner/phases/orchestrator/prompts.ts`** — Two updates:

_Pre-execution step 1 (Dependency Analysis):_ Add `flows.md` to the reading
list, after the `brief.md` instruction:

```typescript
`5. Read \`${epicDir}/flows.md\` — understand the interaction flows. ` +
`Stories should trace to specific flows they implement.`,
```

_Post-execution step 1 (Verify):_ Add `flows.md` to the "What to read"
section, after the story.md acceptance criteria instruction:

```typescript
`3. Read \`${epicDir}/flows.md\` — understand the interaction flows this ` +
`story implements. Verify the implementation produces the behavior ` +
`described in the relevant flows.`,
```

The post-execution step 1 is where the orchestrator checks story correctness.
Adding flows.md here closes the traceability chain: brief → flows → stories →
verification. Without it, the orchestrator verifies against acceptance criteria
(from story.md) but not against the interaction specification those criteria
were derived from.

### 10. Web UI Updates

**`src/planner/web/js/components/PillStrip.jsx`** — Add "flows" pill:

```javascript
const PHASES = [
  { id: "intake", label: "intake" },
  { id: "brief", label: "brief" },
  { id: "flows", label: "flows" },
  { id: "decomposition", label: "decompose" },
  { id: "review", label: "review" },
  { id: "executing", label: "execute" },
];

const PHASE_ORDER = [
  "intake",
  "brief",
  "flows",
  "decomposition",
  "review",
  "executing",
  "completed",
];
```

**`src/planner/web/js/components/ProgressBar.jsx`** (if separate `PHASE_ORDER`
exists): Add `'flows'` between `'brief'` and `'decomposition'`.

### 11. Documentation

**New file: `docs/core-flows.md`**

Spoke document covering:

1. **What flows capture** — interaction specifications between actors and
   systems. Trigger, steps, exit. Product-level, no code.

2. **Pipeline position** — after brief, before decomposition. The brief
   defines the problem; flows define the experience; stories define the work.

3. **Flows-writer subagent** — role, model tier, 6-step workflow with
   rationale for each step:
   - Step 1 (Read): comprehension before action — same principle as all phases
   - Step 2 (Explore): codebase grounding prevents specification drift
   - Step 3 (Align): design decisions through targeted questions, before
     any artifact is drafted. No scouting — single cognitive goal.
   - Step 4 (Re-explore): follow-up investigation based on alignment answers.
     No questions — single cognitive goal. Separating steps 3 and 4 prevents
     the LLM from producing superficial questions knowing it has a scout
     escape hatch.
   - Step 5 (Draft & Review): the review gate — mechanical enforcement of
     human acceptance
   - Step 6 (Finalize): standard termination

4. **Permissions** — why flows-writer is the most tool-rich planning role
   (scouts + questions + review). Comparison to brief-writer (review only)
   and intake (scouts + questions but different purpose).

5. **Downstream references** — table of which phases read flows.md and why.

6. **Design dimensions** — the four dimensions (information hierarchy, user
   journey integration, placement & affordances, feedback & state) and why
   they surface architectural implications, not just aesthetic preferences.

7. **Design principles** — these are captured for future reference, not
   implemented now:
   - Artifact-as-contract pattern and audit trail
   - Product-before-technical ordering rationale
   - Validation gates as a future phase category
   - Agentic workflow progression from fixed pipeline to adaptive ordering

**Update: `docs/architecture.md`**

- Pipeline description: `intake → brief → flows → decomposition → review → executing → completed`
- Phase list: add flows-writer entry
- Artifact cascade diagram: add flows.md layer
- Update the "Pitfalls" section if any flows-specific pitfalls emerge

**Update: `docs/epic-brief.md`**

- Pipeline position diagram: insert `flows` between `brief` and `decomposition`
- Downstream references table: add flows-writer as a consumer of brief.md

**Update: `docs/subagents.md`**

- Task manifest union: add `FlowsWriterTask` variant (role: `"flows-writer"`,
  no role-specific fields beyond `SubagentTaskBase`).
- Role permission matrix: add `flows-writer` row — koan tools:
  `koan_complete_step`, `koan_review_artifact`, `koan_ask_question`,
  `koan_request_scouts`; write/edit: path-scoped to epicDir; notes:
  step 1 (Read) blocks all side-effecting tools.
- Model tiers table: add `flows-writer` to `strong` tier row.
- Back-fill the missing `brief-writer` entry (pre-existing gap from the prior
  phase implementation): `BriefWriterTask` variant, permission row with
  `koan_complete_step`, `koan_review_artifact`, path-scoped write, step 1
  read-only gating.

**Update: `AGENTS.md`**

- Phase list: `intake → brief → flows → decomposition → review → executing → completed`

---

## Implementation Order

The dependency chain:

1. **Type foundations** (`types.ts`) — `SubagentRole`, `EpicPhase`, `ROLE_MODEL_TIER`
2. **Task manifest** (`task.ts`) — `FlowsWriterTask` interface + union
3. **Runtime context** (`runtime-context.ts`) — `flowsWriterStep` field
4. **Permissions** (`permissions.ts`) — role + step gating + 7th parameter
5. **Call-site update** (`base-phase.ts`) — pass `ctx.flowsWriterStep` to `checkPermission`
6. **Phase + prompts** (`flows-writer/phase.ts`, `flows-writer/prompts.ts`)
7. **Dispatch** (`dispatch.ts`) — route to `FlowsWriterPhase`
8. **Driver** (`driver.ts`) — insert phase in pipeline
9. **Downstream prompts** (decomposer, planner, orchestrator)
10. **Web UI** (PillStrip, ProgressBar)
11. **Documentation** (core-flows.md, architecture.md, epic-brief.md, subagents.md, AGENTS.md)

---

## Files Summary

| Action | File                                            | What                                                                          |
| ------ | ----------------------------------------------- | ----------------------------------------------------------------------------- |
| Modify | `src/planner/types.ts`                          | Add `"flows-writer"` to SubagentRole, `"flows"` to EpicPhase, ROLE_MODEL_TIER |
| Modify | `src/planner/lib/task.ts`                       | Add `FlowsWriterTask` + union member                                          |
| Modify | `src/planner/lib/runtime-context.ts`            | Add `flowsWriterStep: number` field + init to 0                               |
| Modify | `src/planner/lib/permissions.ts`                | Add `flows-writer` role, step 1 gating, PLANNING_ROLES, 7th param             |
| Modify | `src/planner/phases/base-phase.ts`              | Pass `ctx.flowsWriterStep` as 7th arg to `checkPermission`                    |
| New    | `src/planner/phases/flows-writer/phase.ts`      | FlowsWriterPhase (6 steps, review gate on step 5)                             |
| New    | `src/planner/phases/flows-writer/prompts.ts`    | System prompt + 6-step guidance                                               |
| Modify | `src/planner/phases/dispatch.ts`                | Add `"flows-writer"` case + import                                            |
| Modify | `src/planner/driver.ts`                         | Insert flows phase between brief and decomposition                            |
| Modify | `src/planner/phases/decomposer/prompts.ts`      | Add flows.md to reading list + strict rules                                   |
| Modify | `src/planner/phases/planner/prompts.ts`         | Add flows.md to reading list                                                  |
| Modify | `src/planner/phases/orchestrator/prompts.ts`    | Add flows.md to pre-exec + post-exec step 1                                   |
| Modify | `src/planner/web/js/components/PillStrip.jsx`   | Add "flows" pill + PHASE_ORDER                                                |
| Modify | `src/planner/web/js/components/ProgressBar.jsx` | Add "flows" to PHASE_ORDER (if separate)                                      |
| New    | `docs/core-flows.md`                            | Spoke document: flows artifact, subagent, design principles                   |
| Modify | `docs/architecture.md`                          | Pipeline + phase list + artifact cascade                                      |
| Modify | `docs/epic-brief.md`                            | Pipeline position + downstream references                                     |
| Modify | `docs/subagents.md`                             | FlowsWriterTask + permission row + model tier; back-fill brief-writer         |
| Modify | `AGENTS.md`                                     | Phase list update                                                             |
