# `--koan-debug`: Step Prompt Visibility

> **Date:** 2026-03-26
> **Scope:** Add a parent-session CLI flag `--koan-debug` that surfaces
> verbatim step guidance text in the koan web UI activity feed. Lays the
> minimal extensibility seam for future per-tool debug rendering (bash, read,
> grep, find, etc.). No new persistence infrastructure; reuses data already
> captured in the audit pipeline.

---

## 1. Objective

When a developer invokes koan with `--koan-debug`, the activity feed shows
the exact step guidance text returned by each `koan_complete_step` call as an
expandable body on the step line. This allows developers to audit the prompts
being sent to LLM subagents without altering the pipeline logic or normal-mode
output.

---

## 2. Non-Goals

- **Not a full LLM context window dump.** Only koan-controlled fragments
  (step guidance from `formatStep`, system prompt from `BasePhase`) are
  accessible via the extension API. The full messages array (conversation
  history, accumulated tool results) is assembled internally by pi and is
  not exposed. The plan does not attempt to capture what pi cannot surface.

- **Not a general logging overhaul.** `koan.log` is unchanged. No new
  file types are added for this iteration.

- **Not a streaming/real-time diff viewer.** Step prompts are displayed as
  static expandable text in the activity feed — no syntax highlighting,
  diffing, or side-by-side comparison.

- **No changes to normal (non-debug) mode output.** Audit event schemas,
  `Projection`, `state.json`, `ipc.json`, and all UI behaviour are identical
  to today when `--koan-debug` is absent.

- **No bash/read/grep/find debug output in this iteration.** The extensibility
  seam for future tool-output debug is defined but not activated.

---

## 3. Constraints

- The architecture invariant "don't pass structured data through CLI flags"
  (docs/architecture.md §6) applies. `--koan-debug` is a rendering toggle,
  not task data. It is a bootstrap signal (analogous to `--mode json`),
  not a subagent task parameter, so passing it as a CLI flag to child
  processes is correct. It must NOT go into `task.json`.

- All tool registrations must remain unconditional at init. The debug flag
  cannot gate tool registration.

- Performance must not degrade in non-debug mode. The 50ms audit polling loop
  and `state.json` projection must be unaffected. No new data enters
  `Projection`; step prompt text must not be written to `state.json`.

- Debug gating must be at data-production time (before string serialisation),
  not at render time. Serialising 2–5 KB of step guidance text per step into
  `events.jsonl` unconditionally would add unnecessary I/O.

---

## 4. Architecture Overview

### 4.1 Existing data path (unchanged)

```
BasePhase.handleStepComplete()
  → formatStep(getStepGuidance(step))   ← prompt string created here
  → koan_complete_step tool result
  → extractToolResult()                 ← stores koanResponse on ToolResultEvent
  → events.jsonl append
  → audit-log-formatter.ts             ← koan_complete_step currently filtered out
  → LogLine[] → SSE → ActivityFeed
```

`koanResponse` already carries the step prompt text for koan tools. The
formatter explicitly drops `koan_complete_step` results. The UI never sees
them.

`LogLine` already has a `body?: string` field that renders as expandable
text (used today for thinking cards in `ActivityFeed.jsx`).

### 4.2 Debug path (new)

```
CLI: pi --koan-debug ...
  → extensions/koan.ts: reads flag, sets ctx.debugMode = true
  → koan_plan.execute: passes debugMode into runPipeline()
  → driver.ts: threads debugMode through SpawnOptions
  → subagent.ts: appends --koan-debug to child pi args when debugMode=true

Child process sees --koan-debug → ctx.debugMode = true

audit-log-formatter.ts: readRecentLogs(dir, count, { debug })
  → in debug mode, koan_complete_step NOT filtered
  → step line gets body = koanResponse.join('\n')
  → ActivityFeed renders expandable step card
```

The key insight: `koanResponse` already exists on every `tool_result` event
for `koan_*` tools. No new event type, no new capture logic, no new file.
The only change is a conditional in the formatter's filter.

---

## 5. Implementation Plan

### Phase 1 — Flag registration and plumbing (parent side)

**File: `extensions/koan.ts`**

- Register `--koan-debug` flag unconditionally:
  ```ts
  pi.registerFlag("koan-debug", {
    description:
      "Developer mode: show verbatim step prompts in the activity feed.",
    type: "boolean",
    default: false,
  });
  ```
- In `before_agent_start` handler (subagent mode):
  ```ts
  ctx.debugMode = !!pi.getFlag("koan-debug");
  ```
- In `koan_plan.execute` (parent mode), read the flag and pass it to
  `startWebServer` and `runPipeline`. `startWebServer` is constructed here
  (not inside `runPipeline`), so both calls happen in `koan_plan.execute`:
  ```ts
  const debugMode = !!pi.getFlag("koan-debug");
  const server = await startWebServer(epicDir, { port, token, debugMode });
  // ...
  const result = await runPipeline(epicDir, cwd, extensionPath, log, server, {
    debugMode,
  });
  ```

**File: `src/planner/lib/runtime-context.ts`**

- Add `debugMode: boolean` to `RuntimeContext` interface (default `false`
  in `createRuntimeContext()`).

**File: `src/planner/subagent.ts`**

- Add `debugMode: boolean` (non-optional) to `SpawnOptions`. Non-optional
  is intentional: every `SpawnOptions` literal in `driver.ts` must explicitly
  set it, so TypeScript catches any missed call site at compile time.
- In args construction, after the model flag:
  ```ts
  ...(opts.debugMode ? ["--koan-debug"] : []),
  ```
- In `makeScoutSpawnContext`, forward `debugMode` from parent opts:
  ```ts
  const result = await spawnSubagent(task, scoutSubagentDir, {
    cwd: opts.cwd,
    extensionPath: opts.extensionPath,
    debugMode: opts.debugMode, // ← add
    log,
  });
  ```

**File: `src/planner/driver.ts`**

- `runPipeline` gains a `PipelineOptions` object as its final parameter:
  ```ts
  export async function runPipeline(
    epicDir: string,
    cwd: string,
    extensionPath: string,
    log: Logger,
    webServer: WebServerHandle | null,
    opts: { debugMode: boolean } = { debugMode: false },
  ): Promise<{ success: boolean; summary: string }>;
  ```
- Thread `debugMode` into the `SpawnOptions` at every construction site.
  There are **five** `SpawnOptions` construction sites (each function creates
  one `opts` object shared across all its `spawnTracked` calls):
  - `runSimplePhase` — one `opts` object
  - `runStoryExecution` — one `opts` object shared across planner, executor,
    and post-orchestrator `spawnTracked` calls
  - `runStoryReexecution` — one `opts` object shared across executor and
    post-orchestrator `spawnTracked` calls
  - `runWorkflowOrchestrator` — one `opts` object
  - `runStoryLoop` pre-execution orchestrator block — one `opts` object

  Concrete pattern (same at every site):

  ```ts
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: ..., debugMode };
  ```

> **Typo-safety:** use a single exported constant `export const KOAN_DEBUG_FLAG =
"koan-debug" as const` in a small `src/planner/lib/constants.ts` (or
> similar) file. Import it at both `registerFlag(KOAN_DEBUG_FLAG, ...)` and
> `["--" + KOAN_DEBUG_FLAG]`. This makes the compiler catch divergence.

---

### Phase 2 — Formatter changes (rendering side)

**File: `src/planner/lib/audit-log-formatter.ts`**

`readRecentLogs` gains an optional options parameter:

```ts
export async function readRecentLogs(
  dir: string,
  count = 8,
  opts?: { debug?: boolean },
): Promise<LogLine[]> {
  ...
  return buildChronologicalLog(events, count, opts?.debug ?? false);
}
```

No change to `src/planner/lib/audit.ts` — it barrel-re-exports
`readRecentLogs` from `audit-log-formatter.ts` and the updated signature
propagates automatically.

`buildChronologicalLog` gains a `debug: boolean` parameter. In the
`tool_result` handler inside that function, change:

```ts
// Before (hard filter):
if (e.tool === "koan_complete_step") {
  pendingCalls.delete(e.toolCallId);
  continue;
}

// After (conditional):
if (e.tool === "koan_complete_step") {
  pendingCalls.delete(e.toolCallId);
  if (debug && e.koanResponse?.length) {
    // Attach prompt body to the most recent step line.
    // step_transition fires immediately before koan_complete_step result,
    // so lines[lines.length - 1] is the step line when it exists.
    const last = lines[lines.length - 1];
    if (last?.tool === "step") {
      last.body = e.koanResponse.join("\n");
    }
  }
  continue;
}
```

> **Ordering guarantee:** `step_transition` is emitted by `handleStepComplete`
> before `formatStep()` returns its value, which becomes the tool result text.
> Both appends happen in the same serialised `EventLog.append` promise chain,
> so the order in `events.jsonl` is always: `step_transition` → `tool_result`
> for `koan_complete_step`. The retroactive assignment to `lines[lines.length - 1]`
> is safe because `lines` is local state and no other events push new lines
> between these two events.
>
> **"Phase complete." edge case:** When `handleStepComplete` returns `null`
> (phase done), `koan_complete_step` still fires as a `tool_result` with
> `koanResponse = ["Phase complete."]`, but `step_transition` is NOT emitted
> at that point — `phase_end` is emitted instead. `lines[lines.length - 1]`
> will be a `phase_end` line (if rendered) or a prior step line, not a
> `step` line, so the `last?.tool === "step"` guard silently skips body
> attachment. Correct behaviour, no special case needed.
>
> This retroactive pattern is identical to how `thinking` events attach
> body text to previously-emitted thinking lines in the same loop.

**Call sites of `readRecentLogs` in `server.ts`:**

Two locations poll logs:

1. `pollAgent()` (~line 474) — for agent-level polling; does NOT need debug
   (this feeds the small agent monitor cards).
2. `trackSubagent()` timer (~line 884) — this is the main activity feed source.
   Pass `{ debug: debugMode }` here.

`WebServerOptions` (defined in `src/planner/web/server.ts`) gains a
`debugMode?: boolean` field. `server.ts` stores it as a local constant and
passes it into the `readRecentLogs` call inside the tracking timer.

`koan_plan.execute` in `extensions/koan.ts` passes `debugMode` when calling
`startWebServer` (see Phase 1).

---

### Phase 3 — Extensibility seam for future tool outputs (minimal, no activation)

This phase defines the contract without implementing any per-tool debug
rendering.

**Formatter seam in `audit-log-formatter.ts`**

In `formatPairedResult()` and `formatInFlightCall()`, add an optional hook
point at the end of every non-koan branch:

```ts
// Placeholder for future debug body rendering.
// In debug mode, a per-tool formatter may populate line.body.
// See: formatDebugBody(tool, input, e.debugOutput)
```

No code is added to these functions yet. The comment documents the intended
extension point so future contributors know where to add tool-specific
rendering without reading the history.

**`ToolResultEvent` schema preparation (`audit-events.ts`)**

Add an optional field to `ToolResultEvent`:

```ts
// Reserved for debug mode: bounded preview of tool output content.
// Populated by extractToolResult() when debugMode is active.
// NOT written in normal mode. Never folded into Projection.
debugOutput?: string;
```

**`extractToolResult` in `event-log.ts`**

The function signature gains an optional `debug` flag:

```ts
export function extractToolResult(
  piEvent: PiToolResultEvent,
  opts?: { debug?: boolean },
): ToolResultEvent;
```

When `opts?.debug` is true AND the tool is in a designated set (initially
`bash` only, as a proof of concept):

```ts
const DEBUG_CAPTURE_TOOLS = new Set(["bash"]);
if (opts?.debug && DEBUG_CAPTURE_TOOLS.has(toolName) && !isError) {
  const text = content.find((c) => c.type === "text")?.text ?? "";
  ev.debugOutput =
    text.slice(0, 4096) + (text.length > 4096 ? "\n…[truncated]" : "");
}
```

**Call site update in `extensions/koan.ts`**

The `tool_result` handler must pass `{ debug: ctx.debugMode }` for the seam
to function. Without this, `debugOutput` is never populated regardless of
flag state:

```ts
pi.on("tool_result", (event) => {
  void eventLog.append(
    extractToolResult(event as { ... }, { debug: ctx.debugMode })
  );
});
```

**This field is defined but the formatter does not yet render it.** The
extensibility seam is:

1. `ToolResultEvent.debugOutput?` — capture contract (defined now, unused by
   formatter until Phase 4).
2. `formatDebugBody(tool, input, debugOutput)` — pure formatter function
   (stub comment now, implemented in Phase 4).
3. `LogLine.body` — UI rendering (already works, nothing to add).

Phase 4 (out of scope for this plan) activates the seam for each desired tool.

---

## 6. File-by-File Change Summary

| File                                     | Change                                                                                                                                                                                                                                                            |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extensions/koan.ts`                     | Register `--koan-debug` flag; read in both parent (`koan_plan.execute`) and subagent (`before_agent_start`) modes; pass `debugMode` to `startWebServer` and `runPipeline`; update `tool_result` handler to pass `{ debug: ctx.debugMode }` to `extractToolResult` |
| `src/planner/lib/runtime-context.ts`     | Add `debugMode: boolean` field (default `false`)                                                                                                                                                                                                                  |
| `src/planner/lib/constants.ts` _(new)_   | `export const KOAN_DEBUG_FLAG = "koan-debug" as const`                                                                                                                                                                                                            |
| `src/planner/subagent.ts`                | Add `debugMode: boolean` (non-optional) to `SpawnOptions`; append `--koan-debug` arg conditionally; forward in `makeScoutSpawnContext`                                                                                                                            |
| `src/planner/driver.ts`                  | Add `PipelineOptions` param to `runPipeline`; thread `debugMode` into all five `SpawnOptions` construction sites                                                                                                                                                  |
| `src/planner/web/server.ts`              | Add `debugMode?: boolean` to `WebServerOptions`; pass `{ debug: debugMode }` to `readRecentLogs` in the `trackSubagent` timer                                                                                                                                     |
| `src/planner/lib/audit-log-formatter.ts` | Add `debug` param to `readRecentLogs` and `buildChronologicalLog`; conditionally attach `koanResponse` body to step lines; add extension seam comment in `formatPairedResult`/`formatInFlightCall`                                                                |
| `src/planner/lib/audit-events.ts`        | Add `debugOutput?: string` to `ToolResultEvent`                                                                                                                                                                                                                   |
| `src/planner/lib/event-log.ts`           | Add `opts?: { debug? }` to `extractToolResult`; populate `debugOutput` for bash when debug is on                                                                                                                                                                  |

No changes to: `src/planner/lib/audit.ts` (barrel re-export propagates
updated `readRecentLogs` automatically), `base-phase.ts`, `step.ts`,
`workflow.ts`, `audit-fold.ts`, `ActivityFeed.jsx`, `store.js`, `sse.js`.
The activity feed already renders `LogLine.body` as an expandable card.

---

## 7. Testing Strategy

### Unit tests (add to `tests/`)

**`tests/audit-log-formatter.test.ts`** — new or extend existing:

- `readRecentLogs` with `debug: false` returns no body on step lines when
  `koan_complete_step` events are present in the JSONL.
- `readRecentLogs` with `debug: true` returns `body` matching `koanResponse`
  on the step line that precedes a `koan_complete_step` tool result.
- `readRecentLogs` with `debug: true` when `koanResponse` is empty does not
  set `body` (no empty-string body pollution).
- `buildChronologicalLog` output is byte-identical for non-debug input
  regardless of the `debug` flag.
- `readRecentLogs` with `debug: true` and a `koan_complete_step` result
  where `koanResponse = ["Phase complete."]` (phase-end case) does NOT attach
  a body to any step line (verifies the `last?.tool === "step"` guard).

**`tests/subagent-args.test.ts`** — new:

- `spawnSubagent` with `debugMode: false` produces args that do not include
  `--koan-debug`.
- `spawnSubagent` with `debugMode: true` produces args that include
  `--koan-debug`.

**`tests/event-log.test.ts`** — new or extend existing (covers Phase 3 seam):

- `extractToolResult` with `{ debug: false }` never sets `debugOutput` for
  `bash` tool results.
- `extractToolResult` with `{ debug: true }` and bash output ≤ 4096 chars
  sets `debugOutput` to the full text with no truncation marker.
- `extractToolResult` with `{ debug: true }` and bash output > 4096 chars
  sets `debugOutput` truncated to 4096 chars with `"\n…[truncated]"` appended.
- `extractToolResult` with `{ debug: true }` and `isError: true` does not
  set `debugOutput`.
- `extractToolResult` with `{ debug: true }` for a tool not in
  `DEBUG_CAPTURE_TOOLS` (e.g. `read`) does not set `debugOutput`.

### Integration / manual checks

- Start koan **without** `--koan-debug`. Verify:
  - Step lines in activity feed show step name, no expandable body.
  - `state.json` unchanged from pre-feature baseline.
  - `ipc.json` unchanged.
  - `koan.log` unchanged.

- Start koan **with** `--koan-debug`. Verify:
  - Step lines in activity feed are expandable.
  - Expanded text matches the step title and instructions exactly (check
    against `formatStep` output for that phase/step).
  - Scout subagents also emit step prompts (confirm scouts receive the flag:
    check `stdout.log` of a scout subagentDir for `--koan-debug` in the
    spawned pi args; verify `debugMode: opts.debugMode` is set inside
    `makeScoutSpawnContext`).
  - Multi-step phase: each step transition gets its own body; no body from
    step N contaminates step N+1.

---

## 8. Risks and Mitigations

| Risk                                                                                                                                        | Severity | Mitigation                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Flag string typo creates silent failure (parent registers one string, child spawn uses another)                                             | High     | Single `KOAN_DEBUG_FLAG` constant imported at both sites; TypeScript catches divergence.                                                                                       |
| Missed `SpawnOptions` construction site in `driver.ts` silently skips flag forwarding for one subagent class                                | High     | `SpawnOptions.debugMode` is non-optional (`boolean`, not `boolean?`); every literal must set it or the file fails to compile.                                                  |
| `--koan-debug` propagated to scout subagents but scout step prompts visible only post-mortem in `events.jsonl` (no live UI feed for scouts) | Low      | Expected: scouts have no `trackSubagent` feed. Document in flag description. Acceptable for this iteration.                                                                    |
| `debugOutput` field on `ToolResultEvent` not folded, but future contributor folds it into `Projection` by mistake, bloating `state.json`    | Medium   | Add `// NOTE: not folded — debug-only; never add to Projection` in `audit-events.ts` and a no-op `case "step_prompt"` in `audit-fold.ts fold()` to make the decision explicit. |
| Retroactive body attachment in formatter attaches to wrong line if event ordering changes                                                   | Low      | `EventLog.append` is serialised via promise chain; ordering is guaranteed. Add assertion in test that step body is attached to the correct step index.                         |
| `body` field renders poorly for multi-line prompt text in `ActivityFeed`                                                                    | Low      | `activity-card-body` uses `white-space: pre-wrap` in `layout.css`; no change needed. Verify in manual test.                                                                    |

---

## 9. Rollout

1. Implement Phase 1 (flag plumbing) — no observable behaviour change.
2. Implement Phase 2 (formatter) — feature is live behind `--koan-debug`.
3. Implement Phase 3 (extensibility seam) — schema and comment stubs only.
4. Run unit tests and manual integration checks.
5. Ship. No feature flag, no migration, no deprecation window needed.

Phase 4 (per-tool debug rendering for bash/read/grep/find) is a separate
plan. The extensibility seam in Phase 3 ensures it can be added without
touching any of the files modified here.

---

## 10. Acceptance Criteria

- [ ] `pi --koan-debug` is accepted without error by the parent session.
- [ ] Without `--koan-debug`, activity feed behaviour is identical to today.
- [ ] With `--koan-debug`, each step line in the activity feed has an
      expandable body containing the verbatim step guidance text.
- [ ] The expanded text matches `formatStep(getStepGuidance(step))` output
      for the corresponding step (verified by inspection for intake phase steps
      1 and 2 at minimum).
- [ ] Scout subagents receive `--koan-debug` in their spawn args (verified
      via `stdout.log` grep in a scout subagentDir; confirm forwarding inside
      `makeScoutSpawnContext`).
- [ ] `state.json` does not contain step prompt text in either mode.
- [ ] Unit tests for formatter pass (`debug: false` no body, `debug: true`
      correct body, byte-identical non-debug baseline, "Phase complete." guard).
- [ ] Unit tests for spawn args pass (flag present iff `debugMode: true`).
- [ ] Unit tests for `extractToolResult` pass (debugOutput population,
      truncation at 4096, error guard, non-captured-tool guard).
- [ ] `tsc --noEmit` passes with no new errors.
