# Web UI Architecture

Single-page dashboard served by `server.ts`. Pushes state via SSE; receives
user input via POST. Built with Preact + Zustand — see
`plans/2026-03-16-preact-zustand-rewrite.md` for the full decision record.

---

## Directory layout

```
server.ts          HTTP server, SSE push, WebServerHandle API
server-types.ts    Shared TypeScript types
html/index.html    Shell — <div id="app"> + module script, no static skeleton
css/               Four unchanged stylesheets (variables, layout, components, animations)
dist/app.js        Compiled bundle — generated, not committed
js/
  app.jsx          Entry: render(<App>), connectSSE(), heartbeat interval
  store.js         Zustand store (single source of truth)
  sse.js           SSE connection + store updates
  lib/utils.js     formatTokens, formatElapsed, shortenModel
  lib/api.js       submitAnswers, submitReview (fetch wrappers)
  components/      Preact component tree (see §Component tree below)
```

---

## Build pipeline

esbuild compiles `js/app.jsx` and all imports into `dist/app.js` (single ESM
bundle, ~44KB raw / ~16KB gzip).

**The alias flags are mandatory.** zustand v4 imports from `react` internally.
Without aliasing, esbuild bundles the full React 19 runtime (~17KB) alongside
Preact — two competing VDOM reconcilers that cannot share a hook dispatcher.
The aliases redirect those imports to `preact/compat`:

```
--alias:react=preact/compat --alias:react-dom=preact/compat
```

These appear in both the npm script (`build:web`) and in the `esbuild.build()`
call inside `ensureBundle()` in `server.ts`. If you add them to one, add them
to both.

**On-demand build:** `ensureBundle()` in `server.ts` runs at the top of
`startWebServer()`. It stats `dist/app.js` against the newest file in `js/`
and rebuilds only when stale. Adds ~100ms on first start; skips on subsequent
starts. No manual build step is needed during development — pi loads extensions
from source, so `startWebServer()` is always the entry point.

**CI/test path:** `npm run build` runs `build:web` then `tsc`. The tsc step
does not process JSX; it type-checks the TypeScript source only.

**zustand version:** Pinned to v4 (`^4.5.7`). zustand v5 moved its default
export to `zustand/react`, which imports React at module level and breaks
the esbuild bundle even with the alias.

---

## Data flow

```
server.ts  ──SSE──►  sse.js  ──setState──►  Zustand store  ──selector──►  components
                                                                  │
user action  ◄──fetch──  lib/api.js  ◄──────────────────────────┘
```

1. `server.ts` pushes SSE events on a 2-second polling tick.
2. `sse.js` registers one `addEventListener` per event type. Each handler
   calls `useStore.setState()` — the static method, callable outside
   component context.
3. Components subscribe via `useStore(s => s.slice)`. Zustand shallow-merges
   `setState` calls and notifies only subscribers whose selected slice changed.
   A component reading `s.agents` does not re-render when `s.phase` changes.
4. User actions (form submit, heartbeat) call `lib/api.js` fetch wrappers
   which POST to `/api/answer`, `/api/review`, or `/api/heartbeat`.

`pendingInput` is cleared by the server: a phase transition out of `intake`
clears it in the `phase` handler; `ask-cancelled` / `review-cancelled` clear
it by request ID.

---

## Component tree

```
App
├── ProgressBar          reads intakeProgress.{subPhase,intakeDone}
├── Header
│   ├── PillStrip        reads intakeProgress.{subPhase,intakeDone}
│   └── Timer            reads subagent.startedAt, ticks via useEffect interval
├── main.phase-content
│   └── PhaseContent     dispatch hub (see below)
├── AgentMonitor         reads agents; renders AgentRow per agent
└── Notifications        reads notifications; auto-dismisses via useEffect
```

**PhaseContent dispatch order:**

1. `!phase` → `<Loading topic>`
2. `pendingInput.type === 'ask'` → `<QuestionForm key={requestId}>`
3. `pendingInput.type === 'review'` → `<ReviewForm key={requestId}>`
4. `phase === 'intake'` → dispatches on `intakeProgress.subPhase`:
   - `'context'` or null → `<ContextAnalysis>`
   - `'explore'` → `<ScoutExploration>`
   - `'questions'` or `'spec'` → `<Consolidation>`
5. `phase === 'completed'` → `<Completion>`
6. default → `<Execution phase={phase}>`

`key={requestId}` on forms forces a full remount when a new request arrives,
resetting local selection state without any explicit cleanup.

---

## Server-side changes

**`ensureBundle()`** — async function before `startWebServer()` body. Uses
esbuild JS API via dynamic `await import("esbuild")`. `STATIC_ASSETS` is
constructed inside `startWebServer()` after this call completes (it was at
module scope in the old code; moved because asset loading must follow the build).

**`intake-progress` SSE event** — denormalized event carrying
`{ subPhase: string | null, intakeDone: boolean }`. Pushed from:
- `startAgentPolling()` — after each `agents` push, if subPhase or intakeDone changed
- `handle.pushPhase()` — updates `intakeDone` on every phase transition

Replayed in `replayState()` on SSE reconnect. Allows `PhaseContent`,
`PillStrip`, and `ProgressBar` to all subscribe to the same store slice
(`intakeProgress`) rather than using two different mechanisms.

---

## Conventions

| Convention | Rule |
|---|---|
| JSX attribute | `class`, not `className` (Preact uses HTML attribute names) |
| Hook imports | `import { useState, useEffect } from 'preact/hooks'` |
| Render import | `import { render } from 'preact'` (not `preact/compat`) |
| External setState | `useStore.setState(...)` — static method, works outside components |
| Fragment syntax | `<>…</>` — works because build uses `--jsx=automatic` |
| Zustand merge | `setState` merges shallowly; always replace the full slice, never mutate nested objects |
