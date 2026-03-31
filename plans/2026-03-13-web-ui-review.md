# Plan Review: 2026-03-13-web-ui.md

Read-only analysis. Cross-references every file the plan marks as deleted,
rewritten, or unchanged against actual code.

> **Status:** All significant findings addressed in the 2026-03-14 revision
> of the plan. See revision notes at the top of the plan for summary of
> changes.

---

## Finding 1: `startActivePolling` signature couples to `EpicWidgetController`

**What:** `startActivePolling()` (driver.ts L81–112) takes a `widget: EpicWidgetController`
parameter and calls `widget.update()` directly. The plan says to replace `widget.update()`
calls with `webServer.push*()` calls (§4.2), but doesn't mention that `startActivePolling`
is a standalone function with its own parameter, not a method on the widget. Its signature
must change from `(dir, widget, ...)` to `(dir, webServer, ...)`.

**Where:** `driver.ts` L81–112, plan §4.6.

**Why it matters:** A developer implementing §4.2's mapping table ("replace `widget.update`
→ `webServer.push*`") would miss this function because it's not a call site _on the widget
from the driver_. It's a function that _receives_ the widget. There are 10 call sites of
`startActivePolling` (L132, L160, L204, L231, L257, L285, L317, L339, L376 — all pass
`widget` as second arg). All of them need their second argument changed too.

**Severity:** Significant — omission would cause compile errors, but the plan should make
this refactoring explicit.

---

## Finding 2: `startActivePolling` also needs non-null guard refactoring

**What:** Every `startActivePolling` call site is guarded by `if (widget)`:

```typescript
if (widget) {
  widget.update({ activeSubagent: { ... } });
  stopPolling = startActivePolling(subagentDir, widget, startedAt, "intake");
}
```

The plan replaces `widget` (nullable `EpicWidgetController | null`) with `webServer`
(nullable `WebServerHandle | null`). But all these guard blocks do _two_ things: set the
initial subagent state AND start polling. In the web version, these are separate concerns:

- `pushSubagent()` can fire unconditionally (it's a no-op when no SSE clients are connected)
- `startActivePolling()` should also run unconditionally so the server has data to push

**Where:** driver.ts L127–133 (and 9 similar blocks), plan §4.2, §4.6.

**Why it matters:** If the `if (webServer)` guards are blindly ported, the server's push
behavior becomes identical to the widget's. But the web server _should_ push data even if no
browser is connected yet (SSE replay sends it when a browser connects). The null guard should
change from "has UI?" to "has server?" — and the push methods should not require a connected
client.

**Severity:** Minor — correct behavior follows naturally if pushes are fire-and-forget into
an internal state buffer, but the plan should clarify this design intent.

---

## Finding 3: `reviewStorySketches` reads from filesystem, not from data passed by driver

**What:** The plan's §4.3 says `webServer.requestReview(stories)` replaces
`reviewStorySketches(epicDir, storyIds, ui)`. But `reviewStorySketches` (spec-review.ts L49–55)
receives `epicDir` and `storyIds`, then _reads the filesystem itself_:

```typescript
for (const storyId of storyIds) {
  const storyPath = path.join(epicDir, "stories", storyId, "story.md");
  const content = await fs.readFile(storyPath, "utf-8");
  const firstLine = content.split("\n").find((l) => l.trim().length > 0);
  const title = firstLine?.replace(/^#+\s*/, "").slice(0, 80) ?? storyId;
  entries.push({ storyId, title, include: true });
}
```

The web version needs the server to do this filesystem reading _before_ pushing the
`review` SSE event. The plan's SSE event payload in §3.1 says
`{ requestId, stories: [{ id, title, summary }] }` — where does `summary` come from?
The current code only extracts `title` (first line of story.md), not a summary.

**Where:** `spec-review.ts` L49–55, plan §3.1 (review event), §4.3.

**Why it matters:** The `review` SSE event payload includes `summary` which doesn't exist
in the current data model. Either the plan intends to add summary extraction (scope creep)
or this is a spec error. The `ReviewStory` type in the `WebServerHandle` interface needs to
match what the filesystem actually provides: `{ storyId, title }` — not `{ id, title, summary }`.

**Severity:** Minor — easy to correct during implementation, but the payload mismatch between
§3.1 and the actual filesystem data would cause confusion.

---

## Finding 4: Plan marks `ask-logic.ts` for deletion but its types cross 5 boundaries

**What:** §5.1 lists `ask-logic.ts` for deletion and notes types must be "relocated to
`web/server-types.ts`". But the relocation has non-obvious consequences:

1. `ipc.ts` (marked UNCHANGED) has its own `AskQuestionPayload` and `AskAnswerPayload`
   types that are _structurally compatible but separately defined_ from `ask-logic.ts`'s
   `AskQuestion` and `AskSelection`. Currently, `ipc-responder.ts` manually maps between
   them (L55–61, L87–97).

2. The `AskQuestion` type in `ask-logic.ts` has fields `{ id, question, options: AskOption[],
multi?, recommended? }`. The `ipc.ts` payload has `{ questions: Array<{ id, question,
options: Array<{ label }>, multi?, recommended? }> }`. These are duck-type compatible
   but there's a subtle difference: `AskOption` is `{ label: string }` while the IPC version
   uses inline `{ label: string }`. Any migration must decide: are these the same type or
   deliberately separate?

3. The `OTHER_OPTION` constant and `appendRecommendedTagToOptionLabels` are currently applied
   _inside the TUI rendering code_ (ask-inline-ui.ts L38, ask-tabs-ui.ts L118–127). In the
   web version, the "Other" option must be added either:
   - Server-side (before pushing via SSE) — then the browser is simpler
   - Browser-side (in forms.js) — then the server pushes raw options

   The plan doesn't specify where this transformation happens.

**Where:** `ask-logic.ts`, `ipc.ts`, `ipc-responder.ts`, plan §4.4 note, §5.1.

**Why it matters:** The implementation note in §4.4 correctly identifies this complexity but
leaves it unresolved. Since `ipc.ts` is marked UNCHANGED, the new `server-types.ts` must
provide types that bridge between `ipc.ts`'s wire types and the SSE/POST payload types. The
boundary mapping that currently lives in `ipc-responder.ts` L55–61 and L87–97 must be
preserved in the rewrite.

**Severity:** Significant — getting the type boundary wrong here would either break IPC
compatibility with subagents (catastrophic) or create confusing type mismatches across the
server-types / ipc / browser boundary.

---

## Finding 5: `spawnSubagent` uses `opts.ui` to gate IPC responder — type change cascades

**What:** `subagent.ts` L96–105 uses `if (opts.ui)` to decide whether to start the IPC
responder. The plan says to change `ui?: ExtensionUIContext` to
`webServer?: WebServerHandle` (§5.2). But the IPC responder currently receives
`ExtensionUIContext` directly:

```typescript
void runIpcResponder(opts.subagentDir, opts.ui, ac.signal, opts.scoutContext);
```

The rewritten `runIpcResponder` will need `WebServerHandle` instead. This means
`subagent.ts` → `ipc-responder.ts` → `WebServerHandle` is a transitive dependency.

Currently, `ipc-responder.ts` imports from `../ui/ask/ask-inline-ui.js` and
`../ui/ask/ask-tabs-ui.js`. After the rewrite, it imports from `../web/server-types.js`
and calls `webServer.requestAnswer()`. This import chain change is correctly described
in §5.2 and §10 step 4, but the plan doesn't mention that `runIpcResponder`'s
signature change means the `ScoutSpawnContext` also needs verification — scout
spawning goes through the IPC responder, and scouts don't get a UI/webserver.

Actually, looking closer: scouts are spawned inside `handleScoutRequest` which
currently doesn't use `ui` at all — it uses `scoutCtx.spawnScout()`. The `ui`
parameter is only used in `handleAskRequest`. So the `scoutContext` path is clean.

**Where:** `subagent.ts` L96–105, `ipc-responder.ts` L178 signature, plan §5.2.

**Why it matters:** The plan correctly identifies the cascade but implementers need to know:
only `handleAskRequest` touches the UI/webserver handle. `handleScoutRequest` is UI-agnostic.
The rewritten `runIpcResponder` signature changes from
`(dir, ui: ExtensionUIContext, signal, scoutCtx?)` to
`(dir, webServer: WebServerHandle, signal, scoutCtx?)`.

**Severity:** Minor — correctly handled by the plan's implementation sequence (step 4 before
step 5), but worth noting the scout path stays clean.

---

## Finding 6: No abort-initiated cleanup of pending SSE events after subagent death

**What:** When a subagent dies, `proc.on("close")` calls `abortIpc()` which aborts the
IPC responder. Currently, the TUI ask widget stays rendered until the user dismisses it
(the existing bug noted in the exploration). The plan's §4.4 says `requestAnswer()` rejects
with `AbortError` and the browser receives an `ask-cancelled` SSE event.

But: who sends the `ask-cancelled` event? The plan's `WebServerHandle` interface (§4.1)
has `requestAnswer()` that returns a Promise. If the signal fires, the Promise rejects. The
`ipc-responder.ts` catch block writes `createCancelledResponse()` to IPC. But _who pushes
the `ask-cancelled` SSE event to the browser?_

Options:

1. The `requestAnswer()` implementation detects its own AbortSignal and self-cancels by
   both rejecting AND pushing the SSE event internally.
2. The `ipc-responder.ts` catch block explicitly pushes the event via `webServer.pushX()`.
3. Some other mechanism.

**Where:** Plan §3.1 (`ask-cancelled` event), §4.4 (abort handling), `ipc-responder.ts`
L73–77, `subagent.ts` L107–109.

**Why it matters:** If `requestAnswer()` doesn't internally clean up the `pendingInputs`
map entry AND push `ask-cancelled` on abort, the browser will show a stale question form
that the user can fill out and submit — but the POST handler will get a 409 (request already
resolved). This is the web equivalent of the existing TUI bug where the ask widget stays
rendered after subagent death.

**Severity:** Significant — this is the plan's opportunity to _fix_ the existing TUI bug
(ask widget stays up after subagent exits). The plan describes the right events but doesn't
specify the ownership of the cancel push clearly enough.

---

## Finding 7: Heartbeat design changed but plan still references timeout in §6.5

**What:** The plan was updated to say the pipeline waits indefinitely (§6.5, §9.3) — no
auto-resolution on heartbeat timeout. But §3.2 still lists `POST /api/heartbeat` as a
route, and §6.5 says "Server watchdog checks every 5 seconds; if no heartbeat for 60
seconds" — then contradicts itself by saying the pipeline continues without blocking.

Wait, re-reading the updated plan: §6.5 now says "The server tracks liveness for
observability but does NOT auto-resolve pending inputs on timeout." So the heartbeat is
kept for monitoring only. This is now internally consistent.

**Severity:** Non-issue (resolved in the plan).

---

## Finding 8: `readProjection` data shape not specified for SSE

**What:** `startActivePolling` calls `readProjection(activeSubagentDir)` (driver.ts L91)
which returns projection data:

```typescript
{ step: number, totalSteps: number, stepName: string }
```

This data is used to construct the `activeSubagent` update. The plan says `pushSubagent(info)`
where `info` is `ActiveSubagentInfo`:

```typescript
{ role, storyId?, step, totalSteps, stepName, startedAt }
```

But `readProjection` doesn't return `role`, `storyId`, or `startedAt` — those are set by
the caller (the driver function that spawned the subagent). The polling callback currently
merges these with the projection:

```typescript
widget.update({
  activeSubagent: {
    role,
    storyId,
    step: projection.step,
    totalSteps: projection.totalSteps,
    stepName: projection.stepName,
    startedAt,
  },
});
```

In the web version, `startActivePolling` would need to construct a full
`ActiveSubagentInfo` and call `webServer.pushSubagent(info)`. This means it must either:

- Receive `role`, `storyId`, `startedAt` as parameters (current pattern, works fine)
- Or the web server must track the "current" role/storyId/startedAt and merge internally

The current pattern works — `startActivePolling` already takes `role`, `storyId`, and
`startedAt` as parameters (L83–87). The plan should note that the polling function
constructs full `ActiveSubagentInfo` objects for the push, not partial updates.

**Where:** `driver.ts` L81–112, plan §4.1 (`pushSubagent` signature), §4.6.

**Why it matters:** Minor clarity issue. The current `widget.update()` accepts partial
patches (`EpicWidgetUpdate` with all optional fields). The proposed `pushSubagent(info)` takes
a complete `ActiveSubagentInfo | null`. This is actually a _better_ design (explicit over
implicit), but the polling function must construct the full object each time.

**Severity:** Minor — natural outcome of the interface design.

---

## Finding 9: `ui.notify()` calls in `driver.ts` L502 use `ui` not `ui?`

**What:** Driver L502:

```typescript
ui.notify("Decomposition complete. Review story sketches...", "info");
```

This is _not_ null-guarded (`ui.notify` instead of `ui?.notify`). It's inside a block
guarded by `if (ui && storyIds.length > 0)` (L500). The plan says replace with
`webServer.pushNotification()`. If the plan changes the parameter from `ui` to `webServer`,
this call is inside a guard that checks truthiness, so it's safe — but the implementer must
update the guard from `if (ui && ...)` to `if (webServer && ...)`.

There are 3 `ui?.notify()` calls in driver.ts (L418, L468) and 1 `ui.notify()` (L502 inside
explicit guard). All need updating.

**Where:** `driver.ts` L468, L418, L502, plan §4.5.

**Why it matters:** Trivial — compile-time catch.

**Severity:** Minor.

---

## Finding 10: Plan doesn't address `runEpicPipeline` return type and tool response

**What:** `koan_plan.execute()` in `koan.ts` L129:

```typescript
const result = await runEpicPipeline(
  epicInfo.directory,
  extCtx.cwd,
  extensionPath,
  log,
  ui,
);
return {
  content: [{ type: "text" as const, text: result.summary }],
  details: undefined,
};
```

The plan adds a web server to the pipeline but `koan_plan.execute()` returns only
`result.summary` as text. The web server URL is never communicated to the LLM or user
through the tool result. The plan mentions `pi.exec("open", [url])` to open the browser
but doesn't say what happens if the browser fails to open.

§12 says "Failure to open the browser is a warning, not a fatal error — the server URL is
included in the tool's output." But the tool's `execute()` function currently returns
_only_ `result.summary` — the URL would need to be prepended or added as additional content.

**Where:** `koan.ts` L129–134, plan §12, §2.2.

**Why it matters:** If the browser fails to open and the URL isn't in the tool output, the
user has no way to connect to the web UI. The LLM also can't help the user because it
doesn't know the URL.

**Severity:** Significant — this is the user's only fallback when browser auto-open fails.
The URL should be included in the tool result (e.g., "Pipeline started. Dashboard:
http://127.0.0.1:{port}/?session={token}").

---

## Finding 11: `koan_plan` has no try/catch — server cleanup on error

**What:** `koan_plan.execute()` has no try/catch around `runEpicPipeline()`. The plan puts
`webServer.close()` in `runEpicPipeline`'s `finally` block (§9.4). But the web server is
started _before_ `runEpicPipeline` (§2.2 sequence diagram), inside `koan_plan.execute()`.

If `runEpicPipeline` receives the server handle and closes it in its `finally` block, this
works. But if the server is started in `koan_plan.execute()` and _something fails between
server start and pipeline start_ (e.g., `exportConversation` throws at koan.ts L126),
the server is leaked — nobody closes it.

**Where:** `koan.ts` L118–134, plan §2.2, §9.4.

**Why it matters:** A leaked server holds a port open. The user sees "address already in use"
on the next attempt. The fix is trivial (wrap in try/finally in `execute()` too), but the
plan doesn't mention it.

**Severity:** Significant — port leak on error path.

---

## Finding 12: SSE state replay must include `pendingInput` — verified correct

**What:** Plan §6.3 says the server replays current state on SSE connect. §6.4 says pending
inputs are re-pushed on reconnect. This is correct and complete — a browser refresh during
an active question would:

1. New SSE connects
2. Server replays: `phase`, `stories`, `subagent`, then pending `ask`/`review`
3. Browser reconstructs the question form

This is the fix for the existing TUI limitation (no recovery from accidental terminal close
during question answering).

**Severity:** Non-issue — well designed.

---

## Finding 13: `EpicWidgetController`'s 1-second render timer has no web equivalent

**What:** The widget has a 1-second `setInterval` (epic-widget.ts L206) that re-renders to
keep the elapsed-time display fresh. The plan deletes this widget. In the web UI, elapsed
time for the active subagent must be computed client-side — the server pushes `startedAt`
and the browser calculates elapsed time with `Date.now() - startedAt`.

The plan doesn't explicitly specify this, but it follows naturally from the SSE event design:
the `subagent` event includes `startedAt`, and the browser computes elapsed time locally.
No server-side timer is needed for this.

**Where:** `epic-widget.ts` L206–207, plan §7.1 (header: elapsed time).

**Why it matters:** If a developer tries to replicate the 1-second server-side push, they'd
waste bandwidth. The browser should use `requestAnimationFrame` or `setInterval` locally to
update the elapsed time display. This is natural for web but worth noting since the TUI
needed a server-side timer.

**Severity:** Minor — implicit but correct.

---

## Finding 14: Plan marks `ask-inline-note.ts` for deletion — one function used by ask UIs

**What:** `ask-inline-note.ts` exports `INLINE_NOTE_WRAP_PADDING` and
`buildWrappedOptionLabelWithInlineNote`. These are imported by both `ask-inline-ui.ts` and
`ask-tabs-ui.ts` (the TUI rendering code). Since both consumers are deleted, the deletion
of `ask-inline-note.ts` is safe — no dangling imports.

The plan correctly identifies this (§5.1). The `wrapTextWithAnsi` import from `pi-tui` in
this file is purely for TUI rendering, so no web equivalent is needed.

**Severity:** Non-issue — verified correct.

---

## Finding 15: `config/menu.ts` imports stay but lose sibling files

**What:** The plan keeps `ui/config/menu.ts` and `ui/config/model-selection.ts` (§8.1).
`menu.ts` imports from `model-selection.ts`:

```typescript
import { createModelSelectionComponent } from "./model-selection.js";
```

Both files stay. `koan.ts` imports `openKoanConfig` from `menu.ts`:

```typescript
import { openKoanConfig } from "../src/planner/ui/config/menu.js";
```

After the rewrite, the `ui/` directory would contain _only_ `config/` (with 2 files). The
sibling files (epic-widget, spec-review, ask/) are deleted. This leaves a `ui/` directory
with a single subdirectory. The plan should note this is intentional — the directory structure
looks odd but is correct.

Additionally: `menu.ts` imports from `../../model-config.js` and `../../model-resolver.js`
(which are UNCHANGED). And it uses `ExtensionCommandContext` from pi-coding-agent (a
different type than `ExtensionUIContext`). So `config/menu.ts` has no dependencies on
any deleted file. Clean.

**Where:** `ui/config/menu.ts`, `ui/config/model-selection.ts`, plan §8.1.

**Why it matters:** A developer might question why `ui/` still exists after "deleting
`src/planner/ui/`". The plan should say "delete files in `ui/` except `config/`" rather
than "delete `src/planner/ui/`".

**Severity:** Minor — wording clarity.

---

## Finding 16: `SpawnOptions` exports are used by multiple consumers

**What:** `subagent.ts` exports `SpawnOptions`, `SpawnStoryOptions`, and `SubagentResult`.
The plan says to change `ui?: ExtensionUIContext` to `webServer?: WebServerHandle` in
`SpawnOptions` (§5.2). But `SpawnOptions` might be imported by other files:

```bash
grep -rn 'SpawnOptions' src/planner/ → subagent.ts only
```

`SpawnOptions` is not imported by any other file — it's used internally by the spawn
functions. The public API is the individual spawn functions (`spawnIntake`, `spawnDecomposer`,
etc.), which receive `SpawnOptions` or `SpawnStoryOptions` as their parameter. The callers
(in `driver.ts`) construct these inline:

```typescript
await spawnIntake({
  epicDir,
  subagentDir,
  cwd,
  extensionPath,
  log,
  ui: ui ?? undefined,
});
```

All 9 spawn call sites in `driver.ts` pass `ui: ui ?? undefined`. These all need to change
to `webServer: webServer ?? undefined`.

**Where:** `driver.ts` (9 spawn call sites), `subagent.ts` (SpawnOptions interface).

**Why it matters:** The plan mentions this in §5.2 but doesn't quantify: there are exactly
9 spawn call sites in driver.ts that pass `ui`, plus 1 in `makeScoutSpawnContext` that
deliberately omits `ui` (scouts don't get it). All 9 need updating.

**Severity:** Minor — compile-time enforcement.

---

## Summary

| #   | Finding                                                               | Severity    | Status                                                                      |
| --- | --------------------------------------------------------------------- | ----------- | --------------------------------------------------------------------------- |
| 1   | `startActivePolling` signature needs explicit refactoring             | Significant | ✅ Resolved — replaced with `trackSubagent`/`clearSubagent` (§4.1, §4.6)    |
| 2   | Null-guard semantics: push should work without connected client       | Minor       | ✅ Resolved — state buffered for replay (§4.1, §6.3)                        |
| 3   | `reviewStorySketches` reads filesystem; `summary` field doesn't exist | Minor       | ✅ Resolved — `ReviewStory = { storyId, title }`, no summary (§3.1, §4.3)   |
| 4   | `ask-logic.ts` type relocation has IPC boundary complexity            | Significant | ✅ Resolved — model code relocated, OTHER_OPTION applied server-side (§5.1) |
| 5   | `subagent.ts` → `ipc-responder.ts` cascade is clean for scouts        | Minor       | ✅ Noted in §5.2                                                            |
| 6   | `ask-cancelled` SSE event ownership unclear on abort path             | Significant | ✅ Resolved — server owns all 3 cleanup steps (§4.1, §9.3)                  |
| 7   | Heartbeat design: observability only                                  | Non-issue   | ✅ Clarified in §6.5                                                        |
| 8   | Polling constructs full `SubagentEvent`, not partial updates          | Minor       | ✅ Resolved — explicit type in §3.1, construction in §4.6                   |
| 9   | `ui.notify` vs `ui?.notify` — null-safety                             | Minor       | ✅ Resolved — all 3 sites listed in §4.5                                    |
| 10  | Server URL not in tool result                                         | Significant | ✅ Resolved — URL in tool result text (§12.3)                               |
| 11  | Server port leak between server start and pipeline                    | Significant | ✅ Resolved — `try/finally` in `execute()` (§2.2, §9.2)                     |
| 12  | SSE state replay + pending input re-push: well designed               | Non-issue   | ✅                                                                          |
| 13  | Elapsed time: browser-local computation                               | Minor       | ✅ Implicit — `startedAt` in `SubagentEvent` (§3.1)                         |
| 14  | `ask-inline-note.ts` deletion: clean                                  | Non-issue   | ✅                                                                          |
| 15  | `ui/` directory partially deleted                                     | Minor       | ✅ Resolved — "delete everything except `config/`" (§5.1)                   |
| 16  | 9 spawn call sites need `ui:` → `webServer:`                          | Minor       | ✅ Quantified in §5.2                                                       |

**All findings resolved in the 2026-03-14 plan revision.**
