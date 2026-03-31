# Epic Brief Phase

Insert an epic brief generation phase between intake and decomposition, with
an IPC-based artifact review mechanism and markdown-rendering web UI.

---

## Design Decisions

### The epic brief is a product-level anchor artifact

The brief captures the **what and why** — problem, context, goals, constraints.
It deliberately excludes UI flows, technical architecture, and implementation
details. This keeps it compact, stable, and reusable as a correctness standard
for all downstream phases.

The brief is the most-referenced artifact in the pipeline. Every phase from
decomposition through execution can consult it to stay aligned with the
original problem.

### "Accept" is verbatim text, not a special parameter

The artifact review response is always a single text string. When the user
clicks "Accept" in the web UI, the response sent back is literally `"Accept"`.
When the user types feedback, the response is their text.

This keeps the tool interface uniform and agile. The LLM processes both cases
the same way: read the response, decide whether to revise or proceed. No
branching protocol, no special fields.

### Artifact review is a reusable IPC mechanism

The review tool is not epic-brief-specific. It presents any markdown artifact
for review and collects free-form feedback. Future phases (e.g., core-flows
equivalent, tech-plan equivalent) use the same mechanism: write artifact →
invoke review → process feedback → loop or proceed.

### Downstream phases read files, not embedded content

Instead of embedding context.md or brief.md content in prompts, agents receive
a nudge to read these files themselves. This keeps prompts stable across
artifact evolution and gives agents the current file content (not a snapshot
from spawn time).

### Client-side markdown rendering

The web UI renders raw markdown client-side. No backend pre-parsing, no HTML
generation on the server. This keeps the backend simple and lets the rendering
evolve independently (e.g., adding mermaid support later without server changes).

---

## Changes

### 1. IPC Protocol — New "artifact-review" message type

**File: `src/planner/lib/ipc.ts`**

Add a third discriminated union member alongside `ask` and `scout-request`:

```typescript
interface ArtifactReviewPayload {
  artifactPath: string; // relative path within epic dir (e.g., "brief.md")
  content: string; // raw markdown content of the artifact
  description?: string; // optional context for the reviewer
}

interface ArtifactReviewResponse {
  id: string;
  respondedAt: string;
  feedback: string; // "Accept" or free-form text
}

interface ArtifactReviewIpcFile {
  type: "artifact-review";
  id: string;
  createdAt: string;
  payload: ArtifactReviewPayload;
  response: ArtifactReviewResponse | null;
}
```

Update `IpcFile` union: `AskIpcFile | ScoutIpcFile | ArtifactReviewIpcFile`.

Add factory: `createArtifactReviewRequest(payload)` → `ArtifactReviewIpcFile`.

**Update `pollIpcUntilResponse`** — add a third exit condition for the new type:

```typescript
if (
  current.type === "artifact-review" &&
  current.response !== null &&
  current.id === ipc.id
) {
  outcome = "answered";
  finalIpc = current;
  break;
}
```

This sits alongside the existing `"ask"` and `"scout-request"` conditions.
Without it, the subagent poll loop never detects the parent's response and
blocks indefinitely.

### 2. LLM Tool — `koan_review_artifact`

**New file: `src/planner/tools/review-artifact.ts`**

Tool the LLM calls to present a written artifact for human review.

**Parameters:**

```typescript
{
  path: string;          // file path of the artifact to review
  description?: string;  // optional context for the reviewer
}
```

**Execution flow** (structurally identical to `koan_ask_question`):

1. Read the file at `path` to get raw markdown content
2. Create `ArtifactReviewIpcFile` with the content
3. Write `ipc.json` (atomic)
4. Poll until response appears
5. Return the feedback string to the LLM

**Tool response to LLM:**

```
User feedback:
Accept

--- or ---

User feedback:
The goals section should include a specific metric for latency. Also,
constraint #3 about "no new architectural choices" feels too restrictive
— we discussed allowing a new queue system in the intake phase.
```

The LLM sees plain text. If it says "Accept", the LLM calls
`koan_complete_step`. If it's feedback, the LLM revises the artifact and
calls `koan_review_artifact` again.

**Registration:** via `registerReviewArtifactTool(pi, ctx)` following the
same pattern as `registerAskTools`.

### 3. IPC Responder — Handle "artifact-review" type

**File: `src/planner/lib/ipc-responder.ts`**

Add `handleArtifactReviewRequest` function (mirrors `handleAskRequest`):

1. Extract payload from ipc file
2. Call `webServer.requestArtifactReview(payload, signal)`
3. Write response back to `ipc.json`

Add third branch in the poll loop:

```typescript
if (ipc.type === "artifact-review") {
  await handleArtifactReviewRequest(subagentDir, ipc, webServer, signal);
}
```

### 4. Web Server — Artifact review endpoint and SSE

**File: `src/planner/web/server-types.ts`**

Add types:

```typescript
interface ArtifactReviewEvent {
  requestId: string;
  artifactPath: string;
  content: string; // raw markdown
  description?: string;
}

interface ArtifactReviewFeedback {
  feedback: string; // "Accept" or free-form text
}
```

Add to `WebServerHandle` interface:

```typescript
requestArtifactReview(
  payload: ArtifactReviewPayload,
  signal: AbortSignal,
): Promise<ArtifactReviewFeedback>;
```

**File: `src/planner/web/server.ts`**

- `requestArtifactReview`: creates Promise in `pendingInputs` with
  `type: "artifact-review"`, pushes SSE event `"artifact-review"`.
- New POST endpoint `/api/artifact-review`:
  validates `token` (403 if mismatch), `requestId`, and `feedback`;
  resolves the pending promise. Follows the same session-token validation
  pattern as `/api/answer` and `/api/review`.
- SSE cancel event: `artifact-review-cancelled`.
- **Update `replayState()`**: add `"artifact-review"` branch to the
  `pendingInputs` iteration so artifact-review state survives SSE
  reconnects:
  ```typescript
  else if (entry.type === "artifact-review") {
    write("artifact-review", {
      requestId,
      artifactPath: entry.payload.artifactPath,
      content: entry.payload.content,
      description: entry.payload.description,
    });
  }
  ```
  Without this, a browser reconnect during an active review loses the
  pending form and stalls the pipeline.

### 5. Web UI — Markdown viewer + feedback form

**New dependency: `marked`** (npm install)

A lightweight markdown-to-HTML renderer. No backend coupling. Future mermaid
support can be added via a custom renderer extension without changing the
component API.

**New file: `src/planner/web/js/components/forms/ArtifactReview.jsx`**

```
┌─────────────────────────────────────────┐
│  Review: Epic Brief                     │
│  ─────────────────────────              │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  │  [rendered markdown content]    │    │
│  │                                 │    │
│  │  ## Summary                     │    │
│  │  This epic covers...            │    │
│  │                                 │    │
│  │  ## Context & Problem           │    │
│  │  Engineers currently lack...    │    │
│  │                                 │    │
│  │  ## Goals                       │    │
│  │  1. **Correctness** — ...       │    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ Feedback (optional)             │    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│                                         │
│  [Send Feedback]          [Accept ✓]    │
│                                         │
└─────────────────────────────────────────┘
```

Component behavior:

- Receives `content` (raw markdown) from the store's `pendingInput.payload`
- Renders markdown client-side using `marked.parse(content)`
- Sets `innerHTML` via `dangerouslySetInnerHTML` — note that `marked` does
  NOT sanitize by default (built-in sanitization was removed in v1.1.0).
  This is acceptable here because content is LLM-generated from a local file,
  not user-provided. If this pattern is reused for user-provided content,
  add DOMPurify
- "Accept" button POSTs `{ token, requestId, feedback: "Accept" }` to
  `/api/artifact-review`
- "Send Feedback" button POSTs `{ token, requestId, feedback: textareaValue }`
  (disabled when textarea is empty)
- After submit, the component unmounts (pendingInput cleared by server event)
- When the LLM revises and re-invokes the tool, a new SSE event arrives and
  the component remounts with updated content

**File: `src/planner/web/js/sse.js`**

Add handler mapping:

```javascript
'artifact-review':           handleArtifactReviewEvent,
'artifact-review-cancelled': handleArtifactReviewCancelledEvent,
```

**File: `src/planner/web/js/store.js`**

Add handlers:

```javascript
export function handleArtifactReviewEvent(d) {
  set({
    pendingInput: {
      type: 'artifact-review',
      requestId: d.requestId,
      payload: { artifactPath: d.artifactPath, content: d.content, description: d.description }
    }
  })
}

export function handleArtifactReviewCancelledEvent(d) {
  set(s => s.pendingInput?.requestId === d.requestId
    ? { pendingInput: null, ... }
    : {}
  )
}
```

**File: `src/planner/web/js/components/PhaseContent.jsx`**

Add dispatch case:

```javascript
if (pending?.type === "artifact-review")
  return <ArtifactReview key={pending.requestId} token={token} />;
```

**File: `src/planner/web/css/components.css`**

Add styles for the artifact review panel: markdown content area with
appropriate typography, code block styling, scrollable container, feedback
textarea, and action buttons.

### 6. Brief-Writer Subagent

**New file: `src/planner/phases/brief-writer/phase.ts`**

Extends `BasePhase`. Role: `"brief-writer"`. Total steps: 3.

Each step has exactly one cognitive goal (per architecture.md pitfall guidance):

Step progression:

- Step 0 → 1: boot (step-first pattern)
- Step 1 (Read): read and comprehend context.md — build a mental model of the
  problem, decisions, codebase findings, and constraints. Read-only; no writing.
- Step 2 (Draft & Review): write brief.md, invoke `koan_review_artifact`. If
  user provides feedback, revise and re-invoke. Loops on step 2 via
  `getNextStep()` override until user responds with "Accept".
  `validateStepCompletion(step=2)` requires at least one `koan_review_artifact`
  call before advancing (ensures the LLM cannot skip review).
- Step 3 (Finalize): phase complete

**New file: `src/planner/phases/brief-writer/prompts.ts`**

System prompt — PM role focused on the "what and why":

```
You are a brief writer for a coding task planner. You read intake context
and produce a compact epic brief — a product-level document that captures
the problem, who's affected, goals, and constraints.

## Your role

You distill intake findings into a clear problem statement. You do NOT
design solutions, plan implementation, or decompose into stories.

## Output

One file: **brief.md** in the epic directory.

## Structure

- **Summary**: 3-8 sentences describing what this epic is about.
- **Context & Problem**: Who's affected, where in the product, the current pain.
- **Goals**: Numbered list of measurable objectives.
- **Constraints**: Hard constraints grounding decisions (from context.md).

Keep the brief compact — under 50 lines. No UI flows, no technical design,
no implementation details.

## Review

After drafting, invoke `koan_review_artifact` to present the brief for
review. If the user provides feedback, revise the brief and present it
again. Continue until the user accepts.
```

Step 1 (Read) guidance:

```
Read `context.md` in the epic directory. Build a thorough mental model of:
- The topic — what is being built or changed
- Codebase findings — architecture, patterns, integration points
- Decisions — every question asked and the user's answer
- Constraints — technical, timeline, compatibility requirements

Do NOT write any files in this step. Comprehend before drafting.
```

Step 2 (Draft & Review) guidance:

```
Draft `brief.md` in the epic directory with the required sections
(Summary, Context & Problem, Goals, Constraints). Keep it under 50
lines. No UI flows, no technical design, no implementation details.

After writing, invoke `koan_review_artifact` with the path to brief.md.

If the user responds with "Accept", call koan_complete_step.
If the user provides feedback, revise brief.md to address the feedback,
then invoke koan_review_artifact again.
```

Step 3 guidance: "Phase complete." (standard termination step)

The phase overrides `getNextStep()` to loop step 2 back to step 2 when
review feedback is received (non-linear progression, same pattern as
the intake confidence loop).

### 7. Task Manifest, Dispatch, and Role Registration

**File: `src/planner/types.ts`**

Add `"brief-writer"` to `SubagentRole` union:

```typescript
export type SubagentRole =
  | "intake"
  | "scout"
  | "decomposer"
  | "orchestrator"
  | "planner"
  | "executor"
  | "brief-writer";
```

Add to `ROLE_MODEL_TIER` — use `"strong"` (same tier as intake and decomposer;
the brief-writer performs similar reasoning-heavy synthesis work):

```typescript
export const ROLE_MODEL_TIER: Record<SubagentRole, ModelTier> = {
  intake: "strong",
  scout: "cheap",
  decomposer: "strong",
  "brief-writer": "strong",
  orchestrator: "strong",
  planner: "strong",
  executor: "standard",
};
```

**File: `src/planner/lib/task.ts`**

Add `BriefWriterTask` interface and extend the union:

```typescript
export interface BriefWriterTask extends SubagentTaskBase {
  role: "brief-writer";
}

export type SubagentTask =
  | IntakeTask
  | ScoutTask
  | DecomposerTask
  | BriefWriterTask
  | OrchestratorTask
  | PlannerTask
  | ExecutorTask;
```

**File: `src/planner/phases/dispatch.ts`**

Add `"brief-writer"` case to the switch (between decomposer and orchestrator):

```typescript
case "brief-writer": {
  const phase = new BriefWriterPhase(pi, ctx, logger, eventLog);
  await phase.begin();
  break;
}
```

Add import: `import { BriefWriterPhase } from "./brief-writer/phase.js";`

Without these three changes, TypeScript compilation fails: `SubagentRole`
does not include `"brief-writer"`, `SubagentTask` has no `BriefWriterTask`
variant, and the exhaustive switch in dispatch.ts errors on the `never`
default branch.

### 8. Permissions (renumbered from §7)

**File: `src/planner/lib/permissions.ts`**

Add `"brief-writer"` to `ROLE_PERMISSIONS`:

```typescript
["brief-writer", new Set([
  "koan_complete_step",
  "koan_review_artifact",
  "edit",
  "write",
])],
```

Add `"brief-writer"` to `PLANNING_ROLES` set (path-scoped to epic directory).

No `koan_ask_question` — the brief-writer uses artifact review, not structured
questions. No `koan_request_scouts` — all codebase context arrives via
context.md from the intake phase.

### 9. Driver — Insert brief phase

**File: `src/planner/types.ts`**

Update `EpicPhase`:

```typescript
export type EpicPhase =
  | "intake"
  | "brief"
  | "decomposition"
  | "review"
  | "executing"
  | "completed";
```

**File: `src/planner/driver.ts`**

Add `runBriefWriter` function (parallel to `runIntake`, `runDecomposer`):

```typescript
async function runBriefWriter(
  epicDir,
  cwd,
  extensionPath,
  log,
  webServer,
): Promise<boolean> {
  const subagentDir = await ensureSubagentDirectory(epicDir, "brief-writer");
  const result = await spawnTracked(
    "brief-writer",
    "brief-writer",
    "brief-writer",
    { role: "brief-writer", epicDir },
    subagentDir,
    undefined,
    opts,
    webServer,
  );
  return result.exitCode === 0;
}
```

Insert between intake and decomposition in `runPipeline`:

```typescript
// After intake succeeds:
await saveEpicState(epicDir, { ...afterIntake, phase: "brief" });
webServer?.pushPhase("brief");

const briefOk = await runBriefWriter(
  epicDir,
  cwd,
  extensionPath,
  log,
  webServer,
);
if (!briefOk) return { success: false, summary: "Brief generation failed" };

const afterBrief = await loadEpicState(epicDir);
await saveEpicState(epicDir, { ...afterBrief, phase: "decomposition" });
webServer?.pushPhase("decomposition");
```

### 10. Prompt Updates — Nudge downstream agents to read brief.md

**File: `src/planner/phases/decomposer/prompts.ts`**

Step 1 guidance — add brief.md to files to read:

```
- `context.md` — intake analysis
- `brief.md` — epic brief: problem statement, goals, and constraints
```

Add to system prompt rules:

```
- MUST NOT invent scope not present in context.md or brief.md.
```

**File: `src/planner/phases/planner/prompts.ts`**

Step 1 guidance — add:

```
3. Read `brief.md` in the epic directory — understand the product-level goals
   and constraints. The plan must serve these goals.
```

**File: `src/planner/phases/orchestrator/prompts.ts`**

Add brief.md reference where context.md is referenced, so the orchestrator
can validate story completion against product goals.

**Note:** The executor reads `plan/context.md` (a different, story-specific
file), not the epic-level context.md. No change needed for the executor — it
works from the plan, which already incorporates brief context via the planner.

### 11. Web UI — PillStrip and ProgressBar update

**File: `src/planner/web/js/components/PillStrip.jsx`**

```javascript
const PHASES = [
  { id: "intake", label: "intake" },
  { id: "brief", label: "brief" },
  { id: "decomposition", label: "decompose" },
  { id: "review", label: "review" },
  { id: "executing", label: "execute" },
];

const PHASE_ORDER = [
  "intake",
  "brief",
  "decomposition",
  "review",
  "executing",
  "completed",
];
```

**File: `src/planner/web/js/components/ProgressBar.jsx`**

ProgressBar has its own hardcoded `PHASE_ORDER` array (separate from
PillStrip). Update it to include `'brief'`:

```javascript
const PHASE_ORDER = [
  "intake",
  "brief",
  "decomposition",
  "review",
  "executing",
  "completed",
];
```

Without this, the progress bar shows incorrect fill percentage during the
brief phase (it won't find `'brief'` in its array, returning index -1 → 0%).

### 12. Documentation

**New file: `docs/artifact-review.md`**

Document the artifact review IPC protocol:

- Message type (`artifact-review`), payload shape, response shape
- Tool interface (`koan_review_artifact`)
- Web UI component behavior
- The "Accept" = verbatim text design decision
- How the review loop works (LLM invokes → feedback → revise → re-invoke)
- Reusability for future artifact types

**New file: `docs/epic-brief.md`**

Document the epic brief artifact:

- What it captures (problem, context, goals, constraints)
- What it excludes (UI flows, tech design, implementation)
- How it fits in the pipeline (after intake, before decomposition)
- How downstream phases reference it
- Design rationale (artifact cascade pattern)

**Update: `docs/architecture.md`**

- Add brief phase to pipeline description
- Add brief-writer to phase list
- Update phase diagram

**Update: `docs/ipc.md`**

- Add artifact-review message type documentation
- Add flow diagram (parallel to existing ask flow and scout flow)

**Update: `AGENTS.md`**

- Update phase list: intake → brief → decomposition → review → executing → completed

---

## Implementation Order

The dependency chain suggests this order:

1. **Type foundations** (`types.ts`) — `SubagentRole`, `EpicPhase`, `ROLE_MODEL_TIER`
2. **IPC types** (`ipc.ts`) — `ArtifactReviewIpcFile` + factory + `pollIpcUntilResponse` update
3. **Task manifest** (`task.ts`) — `BriefWriterTask` interface + union
4. **Tool** (`review-artifact.ts`) — LLM-facing interface
5. **IPC responder** (`ipc-responder.ts`) — parent-side handling
6. **Web server** (`server.ts`, `server-types.ts`) — HTTP/SSE plumbing + `replayState()`
7. **npm install marked** — markdown rendering dependency
8. **Web UI** (`ArtifactReview.jsx`, `store.js`, `sse.js`, `PhaseContent.jsx`, CSS)
9. **Brief-writer phase** (`phase.ts`, `prompts.ts`) — subagent with 3-step workflow
10. **Dispatch** (`dispatch.ts`) — route `"brief-writer"` to phase
11. **Permissions** (`permissions.ts`) — role authorization
12. **Driver** (`driver.ts`) — phase insertion between intake and decomposition
13. **Prompt updates** (decomposer, planner, orchestrator prompts)
14. **PillStrip + ProgressBar** updates
15. **Documentation** (artifact-review.md, epic-brief.md, architecture.md, ipc.md, AGENTS.md)

---

## Files Summary

| Action | File                                                     | What                                                                                  |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Modify | `src/planner/lib/ipc.ts`                                 | Add `ArtifactReviewIpcFile` type + factory + `pollIpcUntilResponse` exit condition    |
| New    | `src/planner/tools/review-artifact.ts`                   | `koan_review_artifact` tool                                                           |
| Modify | `src/planner/lib/ipc-responder.ts`                       | Handle `"artifact-review"` type                                                       |
| Modify | `src/planner/web/server-types.ts`                        | Add review types + `requestArtifactReview`                                            |
| Modify | `src/planner/web/server.ts`                              | SSE event + POST endpoint + `replayState()` branch                                    |
| New    | `src/planner/web/js/components/forms/ArtifactReview.jsx` | Markdown viewer + feedback form                                                       |
| Modify | `src/planner/web/js/store.js`                            | Add artifact-review handlers                                                          |
| Modify | `src/planner/web/js/sse.js`                              | Add SSE event mapping                                                                 |
| Modify | `src/planner/web/js/components/PhaseContent.jsx`         | Add dispatch case                                                                     |
| Modify | `src/planner/web/css/components.css`                     | Artifact review styles                                                                |
| New    | `src/planner/phases/brief-writer/phase.ts`               | Brief-writer phase (3 steps, step 2 loop)                                             |
| New    | `src/planner/phases/brief-writer/prompts.ts`             | System prompt + step guidance                                                         |
| Modify | `src/planner/types.ts`                                   | Add `"brief"` to `EpicPhase` + `"brief-writer"` to `SubagentRole` + `ROLE_MODEL_TIER` |
| Modify | `src/planner/lib/task.ts`                                | Add `BriefWriterTask` interface + union member                                        |
| Modify | `src/planner/phases/dispatch.ts`                         | Add `"brief-writer"` case + import                                                    |
| Modify | `src/planner/lib/permissions.ts`                         | Add `brief-writer` role                                                               |
| Modify | `src/planner/driver.ts`                                  | Insert brief phase in pipeline                                                        |
| Modify | `src/planner/phases/decomposer/prompts.ts`               | Add brief.md reference                                                                |
| Modify | `src/planner/phases/planner/prompts.ts`                  | Add brief.md reference                                                                |
| Modify | `src/planner/phases/orchestrator/prompts.ts`             | Add brief.md reference                                                                |
| Modify | `src/planner/web/js/components/PillStrip.jsx`            | Add "brief" pill + PHASE_ORDER                                                        |
| Modify | `src/planner/web/js/components/ProgressBar.jsx`          | Add "brief" to PHASE_ORDER                                                            |
| New    | `docs/artifact-review.md`                                | Review IPC protocol docs                                                              |
| New    | `docs/epic-brief.md`                                     | Epic brief design docs                                                                |
| Modify | `docs/architecture.md`                                   | Pipeline update                                                                       |
| Modify | `docs/ipc.md`                                            | New message type                                                                      |
| Modify | `AGENTS.md`                                              | Phase list update                                                                     |
| Modify | `package.json`                                           | Add `marked` dependency                                                               |
