# Intake Dashboard UX Flow — Complete Design

> **Scope:** Browser-based UX for the intake phase only (context analysis → scout exploration → elicitation → consolidation).
> **Data sources:** Projection (`state.json`), event log (`events.jsonl`), IPC files (`ipc.json`), scout subagent directories.

---

## State Machine Overview

The browser moves through 6 states during intake. Each state has a distinct visual identity but shares a persistent layout frame.

```
┌──────────┐    SSE connect     ┌───────────────┐   step_transition(1)  ┌──────────────────┐
│ Loading  │ ──────────────────→│    Context     │ ────────────────────→ │      Scout       │
│ (shell)  │                    │   Analysis     │                       │   Exploration    │
└──────────┘                    └───────────────┘                       └──────────────────┘
                                                                              │
                                                                    step_transition(3) +
                                                                    ipc ask request
                                                                              │
┌──────────────┐  all questions   ┌───────────────┐   ask SSE event   ┌──────────────────┐
│Consolidation │←─── answered ────│  Elicitation   │←─────────────────│  Scout → Elicit  │
│              │                  │  (questions)   │                   │   (transition)   │
└──────────────┘                  └───────────────┘                   └──────────────────┘
```

The transition from Scout Exploration to Elicitation is actually seamless — step 3 starts (Gap Analysis & Questions), the intake model reads scout findings, and then asks questions. The browser detects the `ask` SSE event as the moment to shift from progress-watching to interactive mode.

---

## Persistent Layout Frame

Every state renders inside the same page structure. This prevents disorienting full-page transitions.

```
┌─────────────────────────────────────────────────────────────────┐
│  HEADER BAR                                                      │
│  [koan]  Intake · Context Analysis           0m 42s              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  MAIN CONTENT AREA                                               │
│  (changes per state — details below)                             │
│                                                                   │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  STATUS RAIL                                                      │
│  (always visible — agent activity, file operations, events)      │
└─────────────────────────────────────────────────────────────────┘
```

### Header Bar (always visible)

Left side: `koan` wordmark + phase label + step name.
Right side: elapsed timer (computed client-side from `startedAt`).

The phase label uses the 4 user-facing names (Context Analysis, Scout Exploration, Elicitation, Consolidation), not the backend's 3-step names. Mapping:

| Backend step     | Backend stepName         | Dashboard label                 |
| ---------------- | ------------------------ | ------------------------------- |
| 1                | Context Extraction       | Context Analysis                |
| 2                | Codebase Scouting        | Scout Exploration               |
| 3 (before ask)   | Gap Analysis & Questions | Scout Exploration → Elicitation |
| 3 (during ask)   | Gap Analysis & Questions | Elicitation                     |
| 3 (after answer) | Gap Analysis & Questions | Consolidation                   |

The browser determines the sub-phase within step 3 by tracking SSE events: when `ask` arrives → "Elicitation", when answer is submitted → "Consolidation".

### Status Rail (always visible)

A compact bottom panel showing the active agent(s) and recent tool activity. Answers Challenge 4:

```
┌─────────────────────────────────────────────────────────────────┐
│  ● intake · claude-opus-4  step 2/3 · Codebase Scouting           │
│  read src/planner/driver.ts (142L, 6.2k) · 3s ago               │
│  grep "SSE" src/ · 1s ago                                        │
│  bash find . -name "*.ts" (28L, 1.1k) · <1s ago                 │
└─────────────────────────────────────────────────────────────────┘
```

Fields:

- **Agent indicator**: `●` colored dot (green=running, gray=idle) + role + model name + step progress
- **Recent tool calls**: last 3-4 tool invocations from the `logs` SSE event, with relative timestamps
- **No token/cost data** — Projection has `eventCount` but not tokens. Instead: show `events: 47` as a proxy for activity intensity. The event count is meaningful — it roughly correlates with API calls and tells the user "something is happening" even when tool calls are quiet (heartbeats still increment it).

When scouts are running, the rail expands to show scout-level detail (see Challenge 2 below).

---

## State 1: Loading Shell

### What the user sees

The page loads instantly (served from memory, no external assets). The layout frame renders with:

- Header: `koan · Intake` (no step name yet, no timer)
- Main area: centered content — the project name (derived from cwd) and a subtle pulsing indicator
- Status rail: `Connecting...` in muted text

The loading state shows the **conversation topic** if the server can extract it before the first SSE event. Since `conversation.jsonl` is written before the pipeline starts, the server could parse the last user message and include it in the HTML payload or first SSE event. This grounds the user: "Yes, this is about the thing I just asked about."

```
                    ┌──────────────────────────┐
                    │                          │
                    │     koan                 │
                    │                          │
                    │     ○ Initializing...    │
                    │                          │
                    │     "Design the intake   │
                    │      dashboard UX flow"  │
                    │                          │
                    └──────────────────────────┘
```

If no topic is available, the fallback is just the pulsing indicator without the quote.

### Data available from SSE

None yet — SSE connection is being established. The HTML page may inline the session token and a `topic` string if the server extracts one during page generation.

### Interactions

None. The page is passive.

### Duration

1-5 seconds. The gap has two components:

1. SSE connection establishment (~100ms, instant for localhost)
2. Subagent boot time — pi spawns the intake process, loads the extension, model begins responding (~2-8 seconds)

The first SSE event is the state replay (§6.3 of the web UI plan): `phase` event with `"intake"`, then `subagent` event once tracking begins. The `phase` event arrives immediately on SSE connect (server replays buffered state). The `subagent` event arrives when the first polling tick reads a valid `state.json` from the intake subagent directory.

### Transition trigger

First `subagent` SSE event with a non-empty `stepName` → transition to State 2.

Actually, more precisely: the `phase` SSE event arrives first (immediately on connect), which changes the header. Then the `subagent` event arrives 2-4 seconds later with step/progress data, which populates the main content area and status rail. The loading indicator can fade out as soon as the `subagent` event arrives.

---

## State 2: Context Analysis

### What the user sees

The main content area shows a minimal progress view. There's not much to show here — one model is reading the conversation file and extracting structure. The visual emphasis is on calm reassurance that work is happening.

```
┌─────────────────────────────────────────────────────────────────┐
│  koan  Intake · Context Analysis                     0m 12s     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │  ① Context Analysis    ② Exploration              │            │
│  │  ━━━━━━━━━━━━━━━━━━    ─ ─ ─ ─ ─ ─               │            │
│  │  ③ Questions           ④ Consolidation            │            │
│  │  ─ ─ ─ ─ ─ ─ ─        ─ ─ ─ ─ ─ ─ ─             │            │
│  └─────────────────────────────────────────────────┘            │
│                                                                   │
│  Reading your conversation to understand the task...             │
│                                                                   │
│  ┌ Activity ─────────────────────────────────────┐              │
│  │  read conversation.jsonl (847L, 34.2k)         │              │
│  │  ...                                           │              │
│  └────────────────────────────────────────────────┘              │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ● intake · opus-4  step 1/3 · Context Extraction   events: 4   │
│  read conversation.jsonl (847L, 34.2k) · <1s ago                │
└─────────────────────────────────────────────────────────────────┘
```

The **four-phase progress strip** at the top is a horizontal stepper showing all 4 intake phases. Only phase 1 is active (solid bar). Others are dashed/dimmed. This gives the user the full picture of what's coming — answering "how far along are we?" at a glance.

Below the progress strip: a one-line status message ("Reading your conversation...") and a small activity feed showing recent file operations.

### Data available from SSE

```typescript
// subagent event (every 2 seconds):
{ role: "intake", step: 1, totalSteps: 3, stepName: "Step 1/3: Context Extraction", startedAt: 1710504000000 }

// logs event (every 2 seconds):
{ lines: [
  { tool: "read", summary: "conversation.jsonl · 847L/34.2k", highValue: true },
  { tool: "write", summary: "context.md", highValue: true }
]}
```

### Interactions

None. This is a watch-only phase.

### Duration

15-45 seconds. The model reads `conversation.jsonl` (can be large) and writes `context.md`.

### Transition trigger

`subagent` SSE event with `step: 2` and `stepName` containing "Scouting" or "Codebase Scouting".

---

## State 3: Scout Exploration

This is the visually richest state — multiple parallel agents exploring different parts of the codebase.

### Challenge 2 Resolution: Scout Progress Visualization

**How scouts become visible to the browser:**

The current architecture tracks one subagent at a time via `trackSubagent(dir, role)`. During intake step 2, the intake subagent calls `koan_request_scouts`, which triggers the IPC responder to spawn 1-5 scout subagents via `pool()`. Each scout gets its own directory under `epicDir/subagents/scout-{id}-{timestamp}/`.

For the web UI, the web server needs a new SSE event type — `scouts` — that carries parallel scout progress. The IPC responder already knows about scout directories (it creates them in `handleScoutRequest`). When the IPC responder spawns scouts, it should register their directories with the web server for polling. The web server then polls each scout directory at 2-second intervals (same as main subagent polling) and pushes a `scouts` SSE event with all scouts' state.

**New SSE event:**

```typescript
interface ScoutsEvent {
  scouts: Array<{
    id: string; // from ScoutTask.id, e.g. "auth-setup"
    role: string; // from ScoutTask.role, e.g. "auth system auditor"
    status: "running" | "completed" | "failed";
    lastAction: string | null; // from Projection.lastAction
    eventCount: number;
    // No step/totalSteps — scouts are single-step, so step progress is meaningless.
    // Instead, show lastAction as the current activity indicator.
  }>;
}
```

The scout's `role` field (from `ScoutTask.role`) is the meaningful name — "auth system auditor", "API structure analyst", "dependency graph mapper" — not "Scout A". The intake model defines these roles when calling `koan_request_scouts`, and they're specific to what each scout investigates.

### What the user sees

The main area transforms into a scout panel showing each scout as a compact card:

```
┌─────────────────────────────────────────────────────────────────┐
│  koan  Intake · Scout Exploration                    1m 03s     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │  ✓ Context Analysis    ② Exploration              │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━             │            │
│  │  ③ Questions           ④ Consolidation            │            │
│  │  ─ ─ ─ ─ ─ ─ ─        ─ ─ ─ ─ ─ ─ ─             │            │
│  └─────────────────────────────────────────────────┘            │
│                                                                   │
│  Exploring your codebase with 4 scouts...                        │
│                                                                   │
│  ┌ auth-setup ──── auth system auditor ─────────────┐           │
│  │  ● reading src/planner/lib/permissions.ts         │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌ api-structure ── API structure analyst ───────────┐           │
│  │  ● grep "router" src/ (14L, 0.8k)                │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌ test-patterns ── test infrastructure auditor ────┐           │
│  │  ✓ Complete — "Uses vitest with co-located test   │           │
│  │    files. No integration test harness found."     │           │
│  └──────────────────────────────────────────────────┘           │
│  ┌ state-mgmt ──── state management analyst ────────┐           │
│  │  ● bash find . -name "state.json" (12L, 0.4k)    │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ● intake · opus-4  step 2/3 · Codebase Scouting   events: 23  │
│  ● 4 scouts: 1 done, 3 running · haiku-4                        │
└─────────────────────────────────────────────────────────────────┘
```

Each scout card shows:

- **Header**: `id` (kebab-case, machine-readable) + `role` (human-readable description)
- **Status indicator**: `●` spinning/pulsing for running, `✓` for complete, `✗` for failed
- **Current activity** (running): last tool call from the scout's `lastAction` — "reading src/foo.ts", "grep 'pattern' src/", "bash find ..."
- **Completion summary** (done): The scout's `koan_complete_step` summary. This comes from the scout's `state.json` — when status becomes "completed", the `lastAction` or the `phase_end` event's detail field provides the one-line summary.

Cards have a subtle visual state:

- **Running**: left border accent color, slight background highlight
- **Complete**: left border green, muted background, summary text visible
- **Failed**: left border red, error message shown

### Data available from SSE

```typescript
// subagent event (intake subagent, every 2s):
{ role: "intake", step: 2, totalSteps: 3, stepName: "Step 2/3: Codebase Scouting", startedAt: ... }

// scouts event (new, every 2s while scouts are running):
{ scouts: [
  { id: "auth-setup", role: "auth system auditor", status: "running", lastAction: "read src/planner/lib/permissions.ts", eventCount: 8 },
  { id: "api-structure", role: "API structure analyst", status: "running", lastAction: "grep \"router\" src/", eventCount: 5 },
  { id: "test-patterns", role: "test infrastructure auditor", status: "completed", lastAction: null, eventCount: 14 },
  { id: "state-mgmt", role: "state management analyst", status: "running", lastAction: "bash find", eventCount: 3 }
]}

// logs event (intake subagent's own log, not scouts'):
{ lines: [
  { tool: "koan_request_scouts", summary: "scouts:[auth-setup, api-structure, test-patterns, state-mgmt]", highValue: true }
]}
```

### Interactions

None during scout exploration. This is a watch phase.

However: if scout exploration takes a long time (>2 minutes), the user might want to see more detail about what a specific scout is doing. Consider making scout cards expandable — clicking a card reveals the scout's full recent log (last 8 tool calls). This is progressive disclosure: the compact view shows one line per scout, the expanded view shows the scout's activity stream.

### Duration

30 seconds to 3 minutes. Depends on codebase size and number of scouts (1-5). Scouts run in parallel with a concurrency cap of 4.

### Transition trigger

Two things happen in sequence:

1. All scouts complete (or fail) → `scouts` SSE event shows all with terminal status
2. The intake subagent transitions to step 3 → `subagent` event with `step: 3`

Between these, there may be a brief pause (a few seconds) while the intake model reads scout findings. The UI should handle this gracefully: scouts are all done, step 3 hasn't started yet → show a brief "Analyzing scout findings..." message.

The transition to the question state happens when the `ask` SSE event arrives (the intake model has identified gaps and formulated questions).

---

## State 4: Elicitation (Question Answering)

This is the only interactive state. The user answers 1-8 questions that the intake model has crafted based on the conversation and scout findings.

### Challenge 3 Resolution: Question Presentation

**Layout shift:** When the `ask` SSE event arrives, the main content area transitions from the scout cards to a question form. This should be animated — the scout cards slide/fade out, the question form slides/fades in. The scout summary persists in a collapsed section ("4 scouts completed") so the context isn't lost.

**Question form design:**

```
┌─────────────────────────────────────────────────────────────────┐
│  koan  Intake · Elicitation                          2m 17s     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │  ✓ Context Analysis    ✓ Exploration              │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━             │            │
│  │  ③ Questions           ④ Consolidation            │            │
│  │  ━━━━━━━━━━━━━━━━━━    ─ ─ ─ ─ ─ ─ ─             │            │
│  └─────────────────────────────────────────────────┘            │
│                                                                   │
│  ▸ 4 scouts completed                                [expand]    │
│                                                                   │
│  ┌ Questions ─────────────────────────────────────────────────┐ │
│  │                                                             │ │
│  │  We have a few questions to help shape the plan.           │ │
│  │                                                             │ │
│  │  ┌─ 1 of 3 ──── scope ──────────────────────────────────┐ │ │
│  │  │                                                        │ │ │
│  │  │  Should the web dashboard replace the TUI widget       │ │ │
│  │  │  completely, or run alongside it?                      │ │ │
│  │  │                                                        │ │ │
│  │  │  The codebase currently uses pi's ExtensionUIContext    │ │ │
│  │  │  for all rendering. Scout found 8 files with direct    │ │ │
│  │  │  TUI imports.                                          │ │ │
│  │  │                                                        │ │ │
│  │  │  ○ Replace completely — delete all TUI code            │ │ │
│  │  │  ◉ Replace for pipeline, keep TUI for /koan config     │ │ │
│  │  │       (Recommended)                                    │ │ │
│  │  │  ○ Run alongside — user picks TUI or web at runtime    │ │ │
│  │  │  ○ Other ──────────────────────────────────────        │ │ │
│  │  │                                                        │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  │                                                             │ │
│  │  ┌─ 2 of 3 ──── auth ───────────────────────────────────┐ │ │
│  │  │  ...                                                   │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  │                                                             │ │
│  │  ┌─ 3 of 3 ──── persistence ────────────────────────────┐ │ │
│  │  │  ...                                                   │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  │                                                             │ │
│  │  ┌──────────────────────────────────────────────┐          │ │
│  │  │  Accept All Defaults     Submit Answers      │          │ │
│  │  └──────────────────────────────────────────────┘          │ │
│  │                                                             │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ◉ intake · opus-4  step 3/3 · Awaiting answers    events: 31  │
│  Waiting for your input...                                       │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions for questions:**

1. **All questions on one scrollable page, not tabs.** The TUI version uses tabs because terminal height is constrained. The browser has scroll. Showing all questions at once lets the user scan everything, understand the full scope, and answer in any order. With a max of 8 questions, this fits comfortably.

2. **Question cards stacked vertically.** Each question is a card with:
   - **Header**: question number + total, question `id` as a label (e.g., "scope", "auth")
   - **Question text**: the actual question, in prominent text
   - **Context line** (when present): why this question matters, grounded in scout findings. This isn't a separate field in the data — it's part of the question text written by the intake model. The model is already instructed to reference scout findings in questions (see intake prompts step 3). The browser just renders the full question text.
   - **Options**: radio buttons (single-select) or checkboxes (multi-select)
   - **Recommended badge**: "(Recommended)" text next to the recommended option, applied server-side before the SSE event is sent
   - **Other option**: always last, with a text input that appears/expands when selected

3. **"Accept All Defaults" button.** For users who trust the model's recommendations. Clicking it selects the `recommended` option for every question and submits. This is the "skip all questions" affordance. It should be visually secondary to "Submit Answers" (outlined vs filled button, or smaller text link).

4. **"Submit Answers" button.** Primary action. Disabled until every question has at least one selection (or "Other" has text). Shows validation state: "3 of 5 answered" as helper text.

5. **No Cancel button for questions.** The TUI version has Esc=cancel. In the web version, there's no useful cancel semantic — the pipeline is blocked waiting for answers. The user can always close the tab (which causes the pipeline to wait indefinitely per §6.5). If we add Cancel, its behavior would be: submit empty selections, the intake model continues without answers. This could be a "Skip Questions" link in small text below the form.

### Data available from SSE

```typescript
// ask event (one-time, when questions are ready):
{
  requestId: "abc-123-def",
  questions: [
    {
      id: "scope",
      question: "Should the web dashboard replace the TUI widget completely, or run alongside it?\n\nThe codebase currently uses pi's ExtensionUIContext for all rendering. Scout found 8 files with direct TUI imports.",
      options: [
        { label: "Replace completely — delete all TUI code" },
        { label: "Replace for pipeline, keep TUI for /koan config (Recommended)" },
        { label: "Run alongside — user picks TUI or web at runtime" }
      ],
      multi: false,
      recommended: 1
    },
    // ... more questions
  ]
}

// subagent event continues during this time:
{ role: "intake", step: 3, totalSteps: 3, stepName: "Step 3/3: Gap Analysis & Questions", startedAt: ... }
```

Note: the `options` array in the SSE event already includes the "Other (type your own)" option and the "(Recommended)" tag, applied server-side by the functions relocated from `ask-logic.ts` to `web/server-types.ts`. The browser renders exactly what it receives.

Wait — actually, per the web UI plan §5.1: "The `OTHER_OPTION` constant and `appendRecommendedTagToOptionLabels` are applied **server-side** before pushing the `ask` SSE event". So the browser sees options with tags already applied. The browser just needs to detect the "Other" option (last in list, label matches `OTHER_OPTION` constant) and render a text input for it.

### Interactions

- **Select an option**: click radio button / checkbox
- **Select "Other"**: click to reveal/focus a text input field
- **Add a note to any option** (optional): each option could have an expand icon that reveals a text input for additional context. This mirrors the TUI's Tab-to-add-note feature. But for the web version, this might be over-engineering. Simpler: just the "Other" option has a text input. Notes on specific options aren't needed — the user can type a note in the Other field if they want to provide custom input.
- **Accept All Defaults**: one click submits recommended answers for all questions
- **Submit Answers**: validates all questions have selections, sends `POST /api/answer`

### Duration

30 seconds to 5 minutes. Depends on the user. The pipeline is blocked during this time — the status rail should show "Awaiting your input" to make it clear the system is waiting on the user, not processing.

### Transition trigger

User clicks "Submit Answers" or "Accept All Defaults" → browser sends `POST /api/answer` with `{ token, requestId, answers }` → server resolves the pending Promise → intake model receives answers and continues.

---

## State 5: Consolidation

### What the user sees

After the user submits answers, the main content area transitions back to a progress view. The intake model is now writing `decisions.md` — capturing the questions, answers, and remaining unknowns.

```
┌─────────────────────────────────────────────────────────────────┐
│  koan  Intake · Consolidation                        3m 45s     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │  ✓ Context Analysis    ✓ Exploration              │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━             │            │
│  │  ✓ Questions           ④ Consolidation            │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━━            │            │
│  └─────────────────────────────────────────────────┘            │
│                                                                   │
│  Writing project specification from all gathered information...  │
│                                                                   │
│  ┌ Summary ──────────────────────────────────────────┐          │
│  │  Context extracted from conversation               │          │
│  │  4 scouts explored the codebase                    │          │
│  │  3 questions answered                              │          │
│  │  Writing decisions.md...                           │          │
│  └────────────────────────────────────────────────────┘          │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ● intake · opus-4  step 3/3 · Gap Analysis & Questions  e: 38 │
│  write decisions.md · <1s ago                                    │
└─────────────────────────────────────────────────────────────────┘
```

This is a brief wrap-up phase. The user's answers have been received; the model is writing the final specification artifacts.

### Data available from SSE

Same `subagent` and `logs` events as before. Step is still 3/3. The browser knows we're in consolidation because it tracks that the answer was submitted.

```typescript
// logs event:
{
  lines: [
    { tool: "write", summary: "decisions.md", highValue: true },
    { tool: "koan_complete_step", summary: "...", highValue: true },
  ];
}
```

### Interactions

None. Watch-only.

### Duration

5-15 seconds. The model writes `decisions.md` and calls `koan_complete_step`.

### Transition trigger

The intake subagent completes → `subagent-idle` SSE event (or `subagent` with status: "completed") → then a `phase` SSE event with `phase: "decomposition"`.

At this point, intake is done. The dashboard transitions to the decomposition phase (out of scope for this document, but the phase transition animation should smoothly update the header and show a new progress view for decomposition).

---

## State 6: Intake Complete (Transition)

A brief celebration/summary state before decomposition begins.

### What the user sees

```
┌─────────────────────────────────────────────────────────────────┐
│  koan  Intake Complete                               4m 02s     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────────────────────────────────┐            │
│  │  ✓ Context Analysis    ✓ Exploration              │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━             │            │
│  │  ✓ Questions           ✓ Consolidation            │            │
│  │  ━━━━━━━━━━━━━━━━━━    ━━━━━━━━━━━━━━━            │            │
│  └─────────────────────────────────────────────────┘            │
│                                                                   │
│  ✓ Intake complete                                               │
│                                                                   │
│  context.md and decisions.md written.                            │
│  Moving to decomposition...                                      │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ○ idle                                              events: 42 │
└─────────────────────────────────────────────────────────────────┘
```

### Duration

1-3 seconds, then the decomposition phase begins and the dashboard transitions to a new view.

---

## Cross-Cutting Design Decisions

### Challenge 1: The "Empty Browser" Problem — Resolution

**Decision:** Show the layout shell immediately with a centered loading state. Include the conversation topic if extractable.

**Rationale:** The alternative — a blank page or a spinner — wastes the user's attention. By showing the layout frame (header, status rail, progress strip) immediately, the user orients to the page structure before data arrives. The conversation topic ("Design the intake dashboard UX flow") confirms they're looking at the right session.

**Implementation:** The server can extract the topic from `conversation.jsonl` during `koan_plan.execute()` (before the pipeline starts, since the conversation is already exported). Pass it as a data attribute in the HTML template. The browser reads it and displays it in the loading state.

If extraction fails or takes too long, fall back to just the loading indicator. The topic extraction is best-effort — it parses the last user message from the JSONL file (look for the last entry with `role: "user"`, take the first ~100 chars of content).

### Challenge 2: Scout Progress Visualization — Resolution

**Decision:** Scout cards stacked vertically in the main content area. Each card shows id, role, status indicator, and current activity (running) or one-line summary (complete).

**New SSE event type needed:** `scouts` — carries an array of scout states. Pushed by the web server at 2-second intervals when scouts are active. The IPC responder registers scout directories with the web server when spawning scouts.

**Backend change required:** Add `registerScoutDirs(dirs: Map<string, ScoutDir>)` and `clearScouts()` to `WebServerHandle`. The IPC responder calls `registerScoutDirs` after creating scout subagent directories, and `clearScouts` when all scouts complete. The web server polls each registered directory's `state.json` on the same 2-second interval as `trackSubagent`.

**Completion summary:** When a scout completes, its `phase_end` event's `detail` field contains the summary from `koan_complete_step`. The web server reads this from the scout's `events.jsonl` (last `phase_end` event) and includes it in the `scouts` SSE event. The browser shows this as a one-line summary on the completed scout card.

**Why not tabs/accordion for scouts:** With 1-5 scouts, vertical stacking is simpler and shows all scouts at once. Tabs would hide scouts behind clicks. The cards are compact enough (2 lines each) that even 5 scouts fit easily.

### Challenge 3: Question Presentation — Resolution

**Decision:** All questions on one scrollable page (not tabs). Radio/checkbox per question. "Accept All Defaults" button. "Other" with text input.

**Key differences from TUI:**

- No tabs — the TUI uses tabs due to terminal height constraints. The browser scrolls.
- No inline notes on specific options — TUI's Tab-to-add-note is a power feature that adds complexity. The web "Other" text input covers the same need. If a user wants to qualify an answer, they select "Other" and type.
- All questions visible at once — reduces cognitive load vs. navigating tabs. The user sees the full scope immediately.

**Validation:** "Submit Answers" is disabled until every question has a selection. A "3 of 5 answered" counter below the button shows progress. Questions without selections have a subtle red border.

**"Accept All Defaults":** Selects `recommended` for each question (or first option if no recommended). Submits immediately. Shown as a secondary action (text link or outlined button) — not the primary button. This is for users who want to move fast and trust the model.

### Challenge 4: The "Always Visible" Status Bar — Resolution

**Decision:** A fixed bottom rail showing agent status and recent tool calls.

**Contents:**

1. **Agent indicator**: colored dot + role + model + step progress
2. **Event count**: `events: 42` — a proxy for activity (no token data available)
3. **Recent tool calls**: last 2-3 entries from `logs` SSE event, with relative timestamps

**Why event count instead of tokens:** The `Projection` type has `eventCount` but no token fields. `events.jsonl` has individual tool calls but not aggregated token counts. Event count is a reasonable substitute — it increases visibly with activity, and a high count (100+) signals significant work. It's not as meaningful as "$0.42 spent" would be, but it's honest about what data we have.

**Model name formatting:** The `Projection.model` field contains the full model ID (e.g., `anthropic/claude-opus-4-6`). The status rail should display a shortened form: `opus-4` or `haiku-4`. Map from model ID to display name client-side.

**During scout exploration:** The status rail expands to two lines — one for the intake subagent, one for the scout aggregate:

```
│  ● intake · opus-4  step 2/3 · Codebase Scouting   events: 23  │
│  ● 4 scouts (haiku-4): 1 done, 3 running                        │
```

### Challenge 5: Phase Transitions — Resolution

**Decision:** Animate within the persistent layout frame. No page transitions, no route changes, no distinct "pages."

**Mechanism:** The four-phase progress strip at the top of the main content area provides continuity. When a phase completes, its indicator changes from active (accent color, solid bar) to complete (green checkmark). The next phase's indicator becomes active. This is the primary visual signal of progression.

The main content area below the progress strip transitions its content:

- **Context Analysis → Scout Exploration:** The "Reading your conversation..." message fades out, scout cards fade in. Brief crossfade (300ms).
- **Scout Exploration → Elicitation:** Scout cards collapse to a summary line ("4 scouts completed ▸"), question form slides up from below (400ms slide-up). This is the biggest visual shift — from passive watching to active interaction.
- **Elicitation → Consolidation:** Question form slides down (or fades out), replaced by consolidation progress view. Brief "Thank you — writing specification..." message appears.
- **Consolidation → Decomposition:** The entire intake progress strip completes (all four checkmarks), then a new progress view for decomposition replaces it.

**Why not distinct pages:** The pipeline is a continuous process. Page transitions would break the sense of flow and create loading/blank moments. The single-page approach with animated content transitions maintains context and orientation.

**Transition timing:** The animations are triggered by SSE events, not timers. When `step_transition` arrives with step 2, the scout animation starts. When `ask` arrives, the question form appears. When the answer POST resolves, consolidation begins. SSE events are the single source of truth for phase state.

---

## Edge Cases

### No scouts requested

If the intake model determines no scouting is needed (purely conceptual task), step 2 completes immediately with "Scouting skipped." The progress strip shows step 2 as complete, and the browser transitions directly from Context Analysis to step 3. No scout cards are shown. The `scouts` SSE event never fires.

### No questions needed

If the intake model determines the conversation + scout findings are sufficient (no gaps), step 3 completes without an `ask` SSE event. The browser never shows the question form — it goes from Scout Exploration directly to Consolidation. The progress strip shows "Questions" as complete with a "(none needed)" annotation.

### Intake model fails

If the intake subagent crashes (non-zero exit code), the browser receives a `subagent-idle` event or a `notification` event with level "error". The progress strip shows the current phase as failed (red indicator). The main content area shows an error message with the failure detail from `Projection.error`.

### Browser opens mid-phase

SSE replay (§6.3) ensures the browser gets the current state on connect. If the browser opens during scout exploration, it receives the `phase` event, `subagent` event, and `scouts` event in the initial burst. The browser renders the correct state immediately — no "catching up" animation, just the current view.

### User refreshes during questions

SSE replay includes pending inputs (§6.4). The `ask` event is re-pushed on reconnect with the same `requestId`. If the user had partially filled answers, those are lost (browser state is in-memory). The form re-renders fresh. This is acceptable — the user just re-selects their choices. To preserve state across refreshes, we could use `sessionStorage`, but this is a nice-to-have, not essential.

---

## Aesthetic Notes

- **Color palette:** Dark background, high-contrast text. Accent color for active elements. Green for success, red for errors, amber for warnings. Muted gray for inactive/completed elements. Developer-friendly: think VS Code's activity bar, not a marketing dashboard.
- **Typography:** Monospace for tool calls, file paths, model names. Sans-serif for question text and UI chrome. Code-like density — not too much whitespace.
- **Animation:** Subtle and fast (200-400ms). No bouncy/elastic easing. CSS `transition` on opacity and transform. The goal is "smooth" not "playful."
- **Information density:** Developer audience expects density. Don't hide things behind accordions unless there's a clear reason. The status rail is always visible. Scout cards show real file paths. Log entries show actual tool names and byte counts.
