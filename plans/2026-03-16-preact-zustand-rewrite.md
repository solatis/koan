# Web UI: Preact + Zustand Rewrite

> **Date:** 2026-03-16
> **Scope:** Replace vanilla JS DOM-manipulation UI with Preact + Zustand.
> Hard rewrite of all client-side JS files. CSS files unchanged. Server-side
> `server.ts` modified for: on-demand esbuild bundling (`ensureBundle`),
> serving one bundled JS file instead of five, and one new denormalized SSE
> event (`intake-progress`). No tests required.

---

## 1. Problem

The web UI flashes empty and re-renders every ~2 seconds. Root cause: every
render function calls `clearEl(container)` to destroy the entire DOM tree,
then rebuilds from scratch. The server pushes 3–4 SSE events per 2-second
polling tick from independent timers. Each event triggers a full
teardown-rebuild cycle. The browser paints an empty frame between destruction
and reconstruction.

This is a structural problem — the UI has no state diffing, no change
detection, and no concept of incremental updates. Fixing it requires either
bolting diffing onto the existing imperative DOM code, or adopting a
declarative view layer that handles diffing natively.

---

## 2. Approach

Replace the five vanilla JS files (`app.js`, `render.js`, `forms.js`,
`table.js`, `utils.js`) with a Preact + Zustand component tree. The mapping
to the re-frame mental model:

| re-frame       | Preact + Zustand                        |
| -------------- | --------------------------------------- |
| `app-db`       | Zustand store                           |
| `reg-event-db` | SSE handler calling `store.setState(…)` |
| `subscribe`    | `useStore(s => s.slice)` in components  |
| hiccup views   | JSX components                          |
| `reg-fx`       | Side-effect functions (fetch, timers)   |

### 2.1 What changes

- **Deleted:** `js/app.js`, `js/render.js`, `js/forms.js`, `js/table.js`, `js/utils.js`
- **New:** `js/store.js`, `js/sse.js`, `js/app.jsx`, `js/components/*.jsx`, `js/lib/utils.js`
- **Modified:** `html/index.html` (single script entry point), `server.ts` (serve bundled JS)
- **Unchanged:** All four CSS files, `server-types.ts`, `WebServerHandle` interface

### 2.2 What stays the same

- Server-side architecture: SSE push model, polling timers, `WebServerHandle` API — all untouched.
- CSS: All stylesheets kept as-is. Components use the same class names.
- SSE event protocol: Same event names, same JSON payloads — plus one new event (`intake-progress`).
- POST endpoints: `/api/answer`, `/api/review`, `/api/cancel` — same request/response shapes.

---

## 3. Build Pipeline

### 3.1 Tooling: esbuild

The current UI serves raw `.js` files as separate `<script>` tags. Preact JSX
requires a build step. Use esbuild — zero-config, sub-100ms builds, single
dependency. Vite was not chosen because it requires a `vite.config.ts`,
dev-server infrastructure, and adds ~20 transitive packages; esbuild is a
single native binary with no config file.

```
npm install --save-dev esbuild preact zustand
```

Preact and zustand are devDependencies because they are bundled into a single
output file at build time — the server serves the bundle, not the raw
packages. At runtime the browser receives one self-contained file; `node_modules`
is irrelevant.

### 3.2 Build command

Add to `package.json` scripts:

```json
{
  "scripts": {
    "build:web": "esbuild src/planner/web/js/app.jsx --bundle --format=esm --jsx=automatic --jsx-import-source=preact --alias:react=preact/compat --alias:react-dom=preact/compat --outfile=src/planner/web/dist/app.js --minify"
  }
}
```

- `--format=esm`: matches `<script type="module">` in the HTML; enables static imports in the bundle.
- `--jsx=automatic --jsx-import-source=preact`: tells esbuild to use Preact's JSX runtime (`preact/jsx-runtime`) instead of defaulting to `React.createElement`, which would produce a broken bundle.
- `--alias:react=preact/compat --alias:react-dom=preact/compat`: zustand v4 imports from `react` internally. Without these aliases, esbuild bundles the full React runtime (~17KB) alongside Preact — two competing VDOMs that crash at runtime because Preact's reconciler doesn't set up React's hook dispatcher. The aliases route zustand's React imports through Preact's compatibility layer.
- `--minify`: single pass, no separate step needed.

> **Critical:** Both the npm script AND the `ensureBundle()` JS API call in
> `server.ts` must carry identical alias configuration. If either is missing,
> the resulting bundle will contain the full React runtime and crash on first
> `useStore()` call.

Output: `src/planner/web/dist/app.js` — a single self-contained bundle.

> **Wire into build:** Also add `build:web` to the existing `build` script:
> `"build": "npm run build:web && tsc --project tsconfig.build.json"`.
> This covers the test/CI path. The primary development path (pi loading
> the extension from source) is covered by the on-demand build below.

### 3.3 On-demand bundle build in server.ts

**Problem:** Pi loads extensions directly from source. There is no build step
in the developer workflow — the old JS files were committed to git and served
as-is. Adding a required manual `npm run build:web` before every `pi` session
would be a silent-failure footgun: `loadAsset` returns `""` on missing files,
the browser gets an empty JS file, the UI is a blank page, and there is no
error message.

**Solution:** `server.ts` builds the bundle on-demand at server startup if
`dist/app.js` is missing or stale. Uses esbuild's JS API (already installed
as a devDependency). Adds ~100ms to the first server start; subsequent starts
skip the build if the bundle is newer than all source files.

```ts
import * as esbuild from "esbuild";

// Alongside the existing loadAsset function:
async function ensureBundle(): Promise<void> {
  const entryPoint = path.join(__dirname, "js", "app.jsx");
  const outfile = path.join(__dirname, "dist", "app.js");

  // Skip build if bundle exists and is newer than all source files
  try {
    const bundleStat = await fs.stat(outfile);
    const sourceDir = path.join(__dirname, "js");
    const sourceFiles = await fs.readdir(sourceDir, { recursive: true });
    let newest = 0;
    for (const f of sourceFiles) {
      const s = await fs.stat(path.join(sourceDir, String(f)));
      if (s.mtimeMs > newest) newest = s.mtimeMs;
    }
    if (bundleStat.mtimeMs >= newest) return; // bundle is fresh
  } catch {
    // Bundle doesn't exist — build it
  }

  await fs.mkdir(path.join(__dirname, "dist"), { recursive: true });
  await esbuild.build({
    entryPoints: [entryPoint],
    bundle: true,
    format: "esm",
    jsx: "automatic",
    jsxImportSource: "preact",
    alias: {
      react: "preact/compat",
      "react-dom": "preact/compat",
    },
    outfile,
    minify: true,
  });
}
```

Call `ensureBundle()` at the top of `startWebServer()`, **before** the
static asset map is populated:

```ts
export async function startWebServer(
  epicDir: string,
): Promise<WebServerHandle> {
  await ensureBundle(); // build bundle if missing/stale — ~100ms first time, skip thereafter
  // ... rest of the function
}
```

This moves asset loading from module-init time into `startWebServer()` (which
is already async). The `STATIC_ASSETS` map construction moves inside the
function body, after `ensureBundle()` completes:

```ts
const STATIC_ASSETS: Map<string, StaticAsset> = new Map([
  // CSS files unchanged
  [
    "/static/css/variables.css",
    {
      content: loadAsset("css/variables.css"),
      mimeType: "text/css; charset=utf-8",
    },
  ],
  [
    "/static/css/layout.css",
    {
      content: loadAsset("css/layout.css"),
      mimeType: "text/css; charset=utf-8",
    },
  ],
  [
    "/static/css/components.css",
    {
      content: loadAsset("css/components.css"),
      mimeType: "text/css; charset=utf-8",
    },
  ],
  [
    "/static/css/animations.css",
    {
      content: loadAsset("css/animations.css"),
      mimeType: "text/css; charset=utf-8",
    },
  ],
  // Single bundled JS — guaranteed to exist after ensureBundle()
  [
    "/static/js/app.js",
    {
      content: loadAsset("dist/app.js"),
      mimeType: "application/javascript; charset=utf-8",
    },
  ],
]);
```

### 3.4 Server changes — new `intake-progress` event

The current design buries intake sub-phase information inside the `agents`
array (`AgentEntry.subPhase`). The client has to `.find()` the intake agent
and extract it — that's a normalized data structure forcing the UI to
reverse-engineer a derived fact. In an event-sourced model, events should
be denormalized: each event says exactly what changed.

Add a new SSE event type `intake-progress` pushed alongside `agents` during
agent polling. The event carries two fields:

```
event: intake-progress
data: {"subPhase":"explore","intakeDone":false}
```

#### Server implementation

In `server.ts`, add a `currentIntakeProgress` buffer and emit the event from
`startAgentPolling()`:

```ts
// New buffered state (alongside currentPhase, currentStories, etc.)
let currentIntakeProgress: { subPhase: string | null; intakeDone: boolean } = {
  subPhase: null,
  intakeDone: false,
};
```

In `startAgentPolling()`, after the existing `pushEvent("agents", ...)` call,
add:

```ts
// Inside the polling interval callback, after pushEvent("agents", ...):
const intake = Array.from(agents.values()).find((a) => a.role === "intake");
if (intake) {
  const next = {
    subPhase: intake.subPhase,
    intakeDone: currentPhase !== "intake" && currentPhase !== null,
  };
  // Only push if something actually changed — avoid redundant events
  if (
    next.subPhase !== currentIntakeProgress.subPhase ||
    next.intakeDone !== currentIntakeProgress.intakeDone
  ) {
    currentIntakeProgress = next;
    pushEvent("intake-progress", currentIntakeProgress);
  }
}
```

In `replayState()`, add after the `agents` replay:

```ts
if (
  currentIntakeProgress.subPhase !== null ||
  currentIntakeProgress.intakeDone
) {
  write("intake-progress", currentIntakeProgress);
}
```

Also update `intakeDone` in the `pushPhase()` method so it stays accurate
even between polling ticks:

```ts
// Inside handle.pushPhase():
currentIntakeProgress = {
  ...currentIntakeProgress,
  intakeDone: phase !== "intake",
};
pushEvent("intake-progress", currentIntakeProgress);
```

This is ~15 lines of server code. The `agents` event continues to carry
`subPhase` on `AgentEntry` for backwards compatibility (and because it's a
true property of the agent), but the client no longer needs to dig through
the array to find it.

### 3.5 HTML changes

```html
<!-- Before: 5 separate <script defer> tags; load order is implicit (utils before render before app) -->
<!-- After: 1 module script; load order is explicit via ES imports inside the bundle -->
<script>window.__DATA__ = /* __DATA__ */null;</script>
</head>
<body>
  <div id="app"></div>
  <!-- type="module" is inherently deferred — no DOMContentLoaded listener needed in app.jsx -->
  <script type="module" src="/static/js/app.js"></script>
</body>
```

The `<div id="app">` replaces the entire static HTML structure (header,
phase-content, monitor). Preact renders everything. The old `index.html` had
static skeleton markup (pill-strip, agent table, `#phase-content`) that
`render.js` patched in-place; all of that is now component-owned.

---

## 4. Store Design

### 4.1 State shape

```js
// js/store.js
import { create } from "zustand";

export const useStore = create((set) => ({
  // Server-pushed state
  phase: null, // EpicPhase | null
  stories: [], // Array<{ storyId, status }>
  scouts: [], // Array<ScoutState>
  agents: [], // Array<AgentEntry>
  logs: [], // Array<LogLine>
  subagent: null, // SubagentEvent | null
  pendingInput: null, // { type, requestId, payload } | null

  // Denormalized intake progress — pushed by dedicated server event,
  // not derived from agents array. PillStrip and ProgressBar subscribe
  // to this directly without touching the agents list.
  intakeProgress: { subPhase: null, intakeDone: false },

  // Client-only state
  notifications: [], // Array<{ id, message, level }>
  pipelineEnd: null, // { success, summary } | null
}));
```

No actions, no reducers, no dispatch. SSE events are already the action
boundary — adding an action layer would be pure boilerplate. SSE handlers call
`useStore.setState()` directly with the new slice. `useStore.setState` is the
**static** method on the store object (callable from any module without React
context), distinct from the `set` closure available only inside `create()`.
Zustand merges shallowly — unchanged slices keep their reference identity, so
components subscribed to other slices don't re-render.

### 4.2 Selector pattern

Components subscribe to the minimum state they need:

```jsx
// Only re-renders when scouts array reference changes — not on any other state update.
// Using useStore() with no selector (or destructuring the full store) would return a new
// object reference on every setState call, re-rendering every subscriber on every event.
const scouts = useStore((s) => s.scouts);

// Only re-renders when phase changes
const phase = useStore((s) => s.phase);
```

When an `agents` SSE event arrives and calls `setState({ agents: [...] })`,
only components reading `s.agents` re-render. The scout cards, phase content,
and header are untouched.

---

## 5. SSE Connection

### 5.1 Connection module

```js
// js/sse.js
import { useStore } from "./store.js";

export function connectSSE(token) {
  const es = new EventSource(`/events?session=${encodeURIComponent(token)}`);
  // useStore.setState is the static method — callable outside React/Preact component context.
  // This is intentional: sse.js is not a component, it has no access to hooks.
  const set = useStore.setState;

  const handlers = {
    phase: (d) =>
      set({
        phase: d.phase,
        ...(d.phase !== "intake" && { pendingInput: null }),
      }),
    // pendingInput is cleared on phase transition out of 'intake' because the form
    // is only valid during the intake phase; a phase change means the server moved on.
    "intake-progress": (d) => set({ intakeProgress: d }),
    // Denormalized event from server — carries { subPhase, intakeDone } directly.
    // No .find() on agents array needed; PillStrip/ProgressBar subscribe to this slice.
    stories: (d) => set({ stories: d.stories }),
    scouts: (d) => set({ scouts: d.scouts }),
    agents: (d) => set({ agents: d.agents }),
    logs: (d) => set({ logs: d.lines }),
    subagent: (d) => set({ subagent: d }),
    "subagent-idle": () => set({ subagent: null }),
    "pipeline-end": (d) =>
      set((s) => ({
        phase: d.success ? "completed" : s.phase,
        pipelineEnd: d,
      })),
    // pipeline-end uses the functional form of setState (s => ...) to read current phase
    // before deciding whether to overwrite it — avoids a stale closure.
    ask: (d) =>
      set({
        pendingInput: {
          type: "ask",
          requestId: d.requestId,
          payload: d.questions,
        },
      }),
    review: (d) =>
      set({
        pendingInput: {
          type: "review",
          requestId: d.requestId,
          payload: d.stories,
        },
      }),
    "ask-cancelled": (d) =>
      set((s) =>
        s.pendingInput?.requestId === d.requestId
          ? {
              pendingInput: null,
              notifications: [
                ...s.notifications,
                {
                  id: Date.now(),
                  message:
                    "The question was cancelled — the subagent has exited.",
                  level: "warning",
                },
              ],
            }
          : {},
      ),
    "review-cancelled": (d) =>
      set((s) =>
        s.pendingInput?.requestId === d.requestId
          ? {
              pendingInput: null,
              notifications: [
                ...s.notifications,
                {
                  id: Date.now(),
                  message: "The review was cancelled.",
                  level: "warning",
                },
              ],
            }
          : {},
      ),
    // Cancelled handlers use functional form to guard against clearing a *different*
    // pending input that arrived between the cancel and the client processing it.
    notification: (d) =>
      set((s) => ({
        notifications: [
          ...s.notifications,
          { id: Date.now(), message: d.message, level: d.level },
        ],
      })),
  };

  for (const [event, handler] of Object.entries(handlers)) {
    es.addEventListener(event, (e) => {
      try {
        handler(JSON.parse(e.data));
      } catch (err) {
        console.error(`[koan] SSE "${event}":`, err);
      }
    });
  }

  // Surface connection loss to the user — EventSource reconnects silently,
  // but during the gap (3–30s) the UI is stale with no indicator.
  es.onerror = () =>
    set((s) => ({
      notifications: [
        ...s.notifications,
        {
          id: Date.now(),
          message: "Connection lost — reconnecting…",
          level: "warning",
        },
      ],
    }));

  return es;
}
```

Every SSE event is a one-liner state update. The old `app.js` had 12 separate
handler functions that each mutated `state`, then called `renderPhase(state)` —
a full synchronous DOM teardown-rebuild on every event. Here, `setState` is
the only side effect; Preact reacts to state changes automatically.

### 5.2 Heartbeat

Stays as a standalone `setInterval` in the app entry point — it's a pure
side-effect, not state-driven.

---

## 6. Component Tree

### 6.1 Structure

```
App
├── ProgressBar
├── Header
│   ├── PillStrip
│   └── Timer
├── PhaseContent (conditional dispatch)
│   ├── Loading
│   ├── ContextAnalysis
│   ├── ScoutExploration
│   │   ├── ScoutCard (per scout)
│   │   └── CompletedContext
│   ├── Consolidation
│   ├── Execution
│   │   └── StoryRow (per story)
│   ├── Completion
│   ├── QuestionForm
│   │   └── QuestionCard (per question)
│   └── ReviewForm
│       └── ReviewStoryRow (per story)
├── AgentMonitor
│   └── AgentRow (per agent)
└── Notifications
    └── Toast (per notification)
```

### 6.2 File layout

```
js/
  app.jsx              # Entry point: render(<App />), connectSSE(), heartbeat
  store.js             # Zustand store
  sse.js               # SSE connection
  lib/
    utils.js           # formatTokens, formatElapsed, shortenModel
    api.js             # submitAnswers, submitReview (fetch wrappers)
  components/
    App.jsx
    ProgressBar.jsx
    Header.jsx
    PillStrip.jsx
    Timer.jsx
    PhaseContent.jsx   # Conditional dispatch based on phase/pendingInput
    AgentMonitor.jsx
    AgentRow.jsx
    Notifications.jsx
    phases/
      Loading.jsx
      ContextAnalysis.jsx
      ScoutExploration.jsx
      Consolidation.jsx
      Execution.jsx
      Completion.jsx
    forms/
      QuestionForm.jsx
      QuestionCard.jsx
      ReviewForm.jsx
```

### 6.3 Entry point

```jsx
// js/app.jsx
import { render } from "preact";
import { App } from "./components/App.jsx";
import { connectSSE } from "./sse.js";

const data = window.__DATA__;
// __DATA__ is injected by server.ts as: HTML_TEMPLATE.replace("/* __DATA__ */", safeInlineJSON({token, topic}))
// Fallback to query param supports direct URL navigation if __DATA__ injection fails.
const token =
  data?.token || new URLSearchParams(location.search).get("session") || "";

// No DOMContentLoaded needed — <script type="module"> is deferred by spec.
render(
  <App token={token} topic={data?.topic} />,
  document.getElementById("app"),
);
connectSSE(token);

// Heartbeat (pure side-effect, no state)
setInterval(() => {
  fetch("/api/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  }).catch(() => {});
}, 5000);
```

---

## 7. Key Components

### 7.1 App — root layout shell

```jsx
// components/App.jsx
import { ProgressBar } from "./ProgressBar.jsx";
import { Header } from "./Header.jsx";
import { PhaseContent } from "./PhaseContent.jsx";
import { AgentMonitor } from "./AgentMonitor.jsx";
import { Notifications } from "./Notifications.jsx";

export function App({ token, topic }) {
  // The .app wrapper div is required — layout.css styles it as a flex column
  // spanning the viewport. Without it, the fixed header / scrollable main /
  // sticky footer layout breaks.
  return (
    <div class="app">
      <ProgressBar />
      <Header />
      <main class="phase-content">
        <PhaseContent token={token} topic={topic} />
      </main>
      <AgentMonitor />
      <Notifications />
    </div>
  );
}
```

### 7.2 Header — logo, pill strip, timer

```jsx
// components/Header.jsx
import { PillStrip } from "./PillStrip.jsx";
import { Timer } from "./Timer.jsx";

export function Header() {
  // Mirrors the <header> structure from index.html exactly.
  // .header-left groups the logo and pill strip on the left side;
  // the timer floats right via layout.css flex rules.
  return (
    <header class="header">
      <div class="header-left">
        <span class="logo">koan</span>
        <PillStrip />
      </div>
      <Timer />
    </header>
  );
}
```

### 7.3 PhaseContent — the render dispatcher

This replaces the `renderPhase()` function in `render.js`. The old function
was called on every SSE event, called `clearEl(container)` unconditionally,
then rebuilt the entire DOM. This component re-renders only when `phase`,
`subagent`, or `pendingInput` change — and Preact diffs the result against the
existing DOM rather than replacing it.

```jsx
// components/PhaseContent.jsx
import { useStore } from "../store.js";

export function PhaseContent({ token, topic }) {
  const phase = useStore((s) => s.phase);
  const pending = useStore((s) => s.pendingInput);
  // Use the denormalized intake-progress event for ALL intake sub-phase
  // decisions — both content dispatch and pill strip. This eliminates the
  // dual-mechanism issue where PhaseContent used subagent.step (numeric,
  // from the subagent event) while PillStrip used intakeProgress.subPhase
  // (string, from intake-progress). Single source of truth.
  const { subPhase } = useStore((s) => s.intakeProgress);

  // Show loading only before the pipeline has started (phase is null).
  // Once phase is set, always render phase-appropriate content regardless of
  // subagent state — the server calls clearSubagent() between stories, which
  // sets subagent to null while phase is still "executing". Gating on subagent
  // here would flash <Loading> on every story boundary.
  if (!phase) return <Loading topic={topic} />;

  // Forms take priority over phase content — mirrors the guard in renderPhase().
  // key={pending.requestId} forces remount on new request, resetting local
  // form state (selections). Without it, if ask-cancelled + new ask arrive in
  // the same render batch, useState initializer doesn't re-run and stale
  // selections from the previous question set could be submitted.
  if (pending?.type === "ask")
    return <QuestionForm key={pending.requestId} token={token} />;
  if (pending?.type === "review")
    return <ReviewForm key={pending.requestId} token={token} />;

  if (phase === "intake") {
    // Dispatch on intakeProgress.subPhase (string) instead of subagent.step
    // (numeric). Both derive from the same server-side projection.step, but
    // using the denormalized event keeps one mechanism for all intake rendering.
    if (subPhase === "context" || !subPhase) return <ContextAnalysis />;
    if (subPhase === "explore") return <ScoutExploration />;
    return <Consolidation />; // 'questions' or 'spec'
  }

  if (phase === "completed") return <Completion />;

  return <Execution phase={phase} />;
}
```

### 7.4 ScoutExploration — keyed list rendering

```jsx
// components/phases/ScoutExploration.jsx
import { useStore } from "../../store.js";

const COLORS = [
  "var(--blue)",
  "var(--purple)",
  "var(--orange)",
  "var(--yellow)",
  "var(--pink)",
];

export function ScoutExploration() {
  const scouts = useStore((s) => s.scouts);

  return (
    <div class="phase-inner">
      <p class="phase-status">
        Exploring your codebase with {scouts.length} scout
        {scouts.length !== 1 ? "s" : ""}…
      </p>
      {scouts.map((scout, i) => (
        // key={scout.id} gives Preact stable identity per scout across re-renders.
        // Without it Preact uses positional index — adding/removing a scout would
        // patch the wrong card and could flash or corrupt running-state styling.
        <ScoutCard
          key={scout.id}
          scout={scout}
          color={COLORS[i % COLORS.length]}
        />
      ))}
      <CompletedContext scouts={scouts} />
    </div>
  );
}

function ScoutCard({ scout, color }) {
  const cls =
    scout.status === "completed"
      ? "card card-done"
      : scout.status === "failed"
        ? "card card-failed"
        : "card card-running";
  const symbol =
    scout.status === "completed" ? "✓" : scout.status === "failed" ? "✗" : "●";

  return (
    // Note: Preact uses `class`, not React's `className`.
    <div
      class={cls}
      style={
        scout.status === "running" ? { borderLeftColor: color } : undefined
      }
    >
      <div class="card-header">
        <span
          class={`agent-status-${scout.status === "completed" ? "done" : scout.status}`}
        >
          {symbol}
        </span>
        <span
          class="card-title"
          style={scout.status === "running" ? { color } : undefined}
        >
          {scout.id}
        </span>
        <span class="card-role">{scout.role}</span>
      </div>
      <div class="card-body">
        {scout.status === "completed" ? (
          scout.completionSummary
        ) : scout.status === "failed" ? (
          <span style={{ color: "var(--red)" }}>Scout failed</span>
        ) : (
          <span style={{ color: "var(--text-dim)" }}>
            {scout.lastAction || "Starting…"}
          </span>
        )}
      </div>
    </div>
  );
}

function CompletedContext({ scouts }) {
  const completed = scouts.filter(
    (s) => s.status === "completed" && s.completionSummary,
  );
  if (completed.length === 0) return null;

  return (
    <>
      <div class="context-section-label">CONTEXT SO FAR</div>
      <ul class="context-items">
        {completed.map((s) => (
          // key here too — same reason as ScoutCard; list identity matters for diffing.
          <li key={s.id}>
            {s.id}: {s.completionSummary?.slice(0, 100)}
            {(s.completionSummary?.length ?? 0) > 100 ? "…" : ""}
          </li>
        ))}
      </ul>
    </>
  );
}
```

### 7.5 AgentMonitor — derived state in component

```jsx
// components/AgentMonitor.jsx
import { useStore } from "../store.js";
import { formatTokens } from "../lib/utils.js";

export function AgentMonitor() {
  const agents = useStore((s) => s.agents);
  // Derived values computed inline — no separate selector or memoisation needed
  // at this scale. Preact only runs this when agents reference changes.
  const running = agents.filter((a) => a.status === "running").length;
  const done = agents.filter((a) => a.status === "completed").length;
  const failed = agents.filter((a) => a.status === "failed").length;
  const sent = agents.reduce((s, a) => s + (a.tokensSent || 0), 0);
  const recv = agents.reduce((s, a) => s + (a.tokensReceived || 0), 0);

  return (
    <footer class="monitor">
      <div class="agent-table-header">
        <span class="monitor-label">Subagents</span>
        <div class="agent-badges">
          {running > 0 && <span class="badge active">{running}</span>}
          {done > 0 && <span class="badge done">{done}</span>}
          {failed > 0 && <span class="badge failed">{failed}</span>}
        </div>
        <span class="token-totals">
          {sent > 0 || recv > 0
            ? `↑${formatTokens(sent)} ↓${formatTokens(recv)}`
            : ""}
        </span>
      </div>
      <table class="agent-table">
        <thead>
          <tr>
            <th class="col-status"></th>
            <th class="col-agent">agent</th>
            <th class="col-model">model</th>
            <th class="col-parent">parent</th>
            <th class="col-tokens">↑ sent</th>
            <th class="col-tokens">↓ recv</th>
            <th class="col-doing">doing</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => (
            <AgentRow key={a.id} agent={a} />
          ))}
        </tbody>
      </table>
    </footer>
  );
}
```

### 7.6 QuestionForm — local component state for selections

```jsx
// components/forms/QuestionForm.jsx
import { useState } from "preact/hooks";
// Hooks are in 'preact/hooks', not 'preact' — different import path from React.
import { useStore } from "../../store.js";
import { submitAnswers } from "../../lib/api.js";

export function QuestionForm({ token }) {
  const { requestId, payload: questions } = useStore((s) => s.pendingInput);
  // selections is local UI state — it doesn't belong in the global store because
  // it's ephemeral form state that only matters while this component is mounted.
  const [selections, setSelections] = useState(() =>
    new Array(questions.length).fill(null),
  );

  // Check both non-null and non-empty — acceptDefaults() can produce
  // { selectedOptions: [] } for questions with empty options arrays,
  // which is truthy but represents no actual answer.
  const allAnswered = selections.every(
    (s) => s !== null && (s.selectedOptions?.length > 0 || s.customInput),
  );
  const answeredCount = selections.filter(
    (s) => s !== null && (s.selectedOptions?.length > 0 || s.customInput),
  ).length;

  function updateSelection(index, selection) {
    setSelections((prev) => {
      const next = [...prev];
      next[index] = selection;
      return next;
    });
  }

  function acceptDefaults() {
    const answers = questions.map((q) => {
      const idx = q.recommended ?? 0;
      const label = q.options[idx]?.label;
      return { questionId: q.id, selectedOptions: label ? [label] : [] };
    });
    submitAnswers({ token, requestId, answers });
  }

  function submit() {
    const answers = questions.map((q, i) => ({
      questionId: q.id,
      ...(selections[i] || { selectedOptions: [] }),
    }));
    submitAnswers({ token, requestId, answers });
    // pendingInput is cleared by the server's 'ask-cancelled' event or the next
    // phase transition — the component does not clear it directly.
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">A few questions to shape the plan</h2>
      <div class="count-progress">
        {answeredCount} of {questions.length} answered
      </div>

      {questions.map((q, i) => (
        <QuestionCard
          key={q.id}
          question={q}
          index={i}
          total={questions.length}
          selection={selections[i]}
          onSelect={(sel) => updateSelection(i, sel)}
        />
      ))}

      <div class="form-actions">
        <button class="btn btn-secondary" onClick={acceptDefaults}>
          Accept All Defaults
        </button>
        <button
          class="btn btn-primary"
          disabled={!allAnswered}
          onClick={submit}
        >
          Submit Answers
        </button>
        {!allAnswered && (
          <span class="form-helper">
            {questions.length - answeredCount} remaining
          </span>
        )}
      </div>
    </div>
  );
}
```

### 7.7 Completion — pipeline end state

```jsx
// components/phases/Completion.jsx
import { useStore } from "../../store.js";

export function Completion() {
  const pipelineEnd = useStore((s) => s.pipelineEnd);

  return (
    <div class="phase-inner">
      <p class="phase-status">
        {pipelineEnd?.success ? "Pipeline complete ✓" : "Pipeline failed"}
      </p>
      {pipelineEnd?.summary && (
        <div class="summary-list">
          <div class="summary-item">
            <span class={pipelineEnd.success ? "icon-done" : "icon-pending"}>
              {pipelineEnd.success ? "✓" : "✗"}
            </span>
            <span>{pipelineEnd.summary}</span>
          </div>
        </div>
      )}
    </div>
  );
}
```

### 7.8 ReviewForm — story approval/skip

```jsx
// components/forms/ReviewForm.jsx
import { useState } from "preact/hooks";
import { useStore } from "../../store.js";
import { submitReview } from "../../lib/api.js";

export function ReviewForm({ token }) {
  const { requestId, payload: stories } = useStore((s) => s.pendingInput);
  // Track which stories are approved — all approved by default (matches old UI).
  // Using a Set of storyIds for O(1) toggle; convert to arrays on submit.
  const [approved, setApproved] = useState(
    () => new Set(stories.map((s) => s.storyId)),
  );

  function toggle(storyId) {
    setApproved((prev) => {
      const next = new Set(prev);
      if (next.has(storyId)) next.delete(storyId);
      else next.add(storyId);
      return next;
    });
  }

  function approveAll() {
    setApproved(new Set(stories.map((s) => s.storyId)));
  }

  function submit() {
    const approvedList = stories
      .filter((s) => approved.has(s.storyId))
      .map((s) => s.storyId);
    const skippedList = stories
      .filter((s) => !approved.has(s.storyId))
      .map((s) => s.storyId);
    submitReview({
      token,
      requestId,
      approved: approvedList,
      skipped: skippedList,
    });
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">Review story sketches</h2>
      <p class="phase-status">Review stories before execution begins.</p>

      {stories.map((story) => (
        <div
          key={story.storyId}
          class={`review-story ${approved.has(story.storyId) ? "checked" : ""}`}
          onClick={() => toggle(story.storyId)}
        >
          <div class="review-story-checkbox" />
          <span class="review-story-id">{story.storyId}</span>
          <span class="review-story-title"> — {story.title}</span>
        </div>
      ))}

      <div class="form-actions">
        <button class="btn btn-secondary" onClick={approveAll}>
          Approve All
        </button>
        <button class="btn btn-primary" onClick={submit}>
          Submit
        </button>
      </div>
    </div>
  );
}
```

`api.js` must export both fetch wrappers:

```js
// js/lib/api.js
export async function submitAnswers({ token, requestId, answers }) {
  const resp = await fetch("/api/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, requestId, answers }),
  });
  if (!resp.ok) console.error("Failed to submit answers:", await resp.text());
}

export async function submitReview({ token, requestId, approved, skipped }) {
  const resp = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, requestId, approved, skipped }),
  });
  if (!resp.ok) console.error("Failed to submit review:", await resp.text());
}
```

### 7.9 Notifications — auto-dismiss with cleanup

```jsx
// components/Notifications.jsx
import { useEffect } from "preact/hooks";
import { useStore } from "../store.js";

export function Notifications() {
  const notifications = useStore((s) => s.notifications);

  // Each notification gets its own dismiss timer, keyed by the newest
  // notification's ID. Dependency is on the specific ID, not the array
  // length — this avoids the race where rapid-fire notifications keep
  // resetting a single timer and none ever dismiss.
  // Removal is by ID (filter), not position (slice) — concurrent timer
  // callbacks can't accidentally discard the wrong notification.
  useEffect(() => {
    if (notifications.length === 0) return;
    const newest = notifications[notifications.length - 1];
    const timer = setTimeout(() => {
      useStore.setState((s) => ({
        notifications: s.notifications.filter((n) => n.id !== newest.id),
      }));
    }, 5000);
    return () => clearTimeout(timer);
  }, [notifications[notifications.length - 1]?.id]);

  return (
    <div id="notifications">
      {notifications.map((n) => (
        <div key={n.id} class={`notification ${n.level}`}>
          {n.message}
        </div>
      ))}
    </div>
  );
}
```

### 7.10 Timer — self-updating via useEffect

```jsx
// components/Timer.jsx
import { useState, useEffect } from "preact/hooks";
import { useStore } from "../store.js";
import { formatElapsed } from "../lib/utils.js";

export function Timer() {
  const startedAt = useStore((s) => s.subagent?.startedAt);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!startedAt) return;
    // interval is created per startedAt value and cleaned up when startedAt changes
    // (e.g. new subagent starts) or component unmounts. Without the cleanup return,
    // each new subagent would accumulate an additional interval that never stops.
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  if (!startedAt) return <span class="timer">—</span>;
  return <span class="timer">{formatElapsed(now - startedAt)}</span>;
}
```

### 7.11 PillStrip — intake progress pills

```jsx
// components/PillStrip.jsx
import { useStore } from "../store.js";

const PILLS = ["context", "explore", "questions", "spec"];

export function PillStrip() {
  // Reads from the denormalized intake-progress event — no .find() on agents.
  // Only re-renders when subPhase or intakeDone actually change.
  const { subPhase, intakeDone } = useStore((s) => s.intakeProgress);
  const activeIdx = PILLS.indexOf(subPhase || "");

  return (
    <div id="pill-strip">
      {PILLS.map((pill, i) => {
        // pill is done if intake is complete or it comes before the active step
        const cls =
          intakeDone || i < activeIdx
            ? "pill done"
            : i === activeIdx
              ? "pill active"
              : "pill pending";
        return (
          <span key={pill} class={cls} data-pill={pill}>
            {pill}
          </span>
        );
      })}
    </div>
  );
}
```

### 7.12 ProgressBar — progress fill width

```jsx
// components/ProgressBar.jsx
import { useStore } from "../store.js";

const PILLS = ["context", "explore", "questions", "spec"];

export function ProgressBar() {
  // Same denormalized source as PillStrip — no agents array dependency.
  const { subPhase, intakeDone } = useStore((s) => s.intakeProgress);
  const activeIdx = PILLS.indexOf(subPhase || "");
  // donePills counts completed steps; 4 when all done, else however many precede the active pill
  const donePills = intakeDone ? 4 : Math.max(0, activeIdx);
  const pct = (donePills / 4) * 100;

  return (
    <div class="progress-bar">
      <div class="progress-fill" style={{ width: pct + "%" }} />
    </div>
  );
}
```

### 7.13 Loading — initial loading screen

```jsx
// components/phases/Loading.jsx
export function Loading({ topic }) {
  return (
    // Inline styles match renderLoading()'s imperative style assignments exactly
    <div
      class="phase-inner"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: "80px",
      }}
    >
      <div class="spinner" />
      <p class="phase-status" style={{ marginTop: "16px" }}>
        Initializing...
      </p>
      {topic && (
        <div class="topic-card">
          <div class="topic-label">YOUR REQUEST</div>
          <div class="topic-text">{topic}</div>
        </div>
      )}
    </div>
  );
}
```

### 7.14 ContextAnalysis — conversation reading screen

```jsx
// components/phases/ContextAnalysis.jsx
import { useStore } from "../../store.js";

export function ContextAnalysis() {
  const logs = useStore((s) => s.logs);

  return (
    <div class="phase-inner">
      <p class="phase-status">
        Reading your conversation to understand the task...
      </p>
      {logs.length > 0 && (
        // Last 4 log lines — same slice as renderContextAnalysis()
        <div class="activity-feed">
          {logs.slice(-4).map((line, i) => (
            <div key={i} class="activity-line">
              <span class="activity-tool">{line.tool}</span>
              <span>{line.summary || ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 7.15 Consolidation — spec writing screen

```jsx
// components/phases/Consolidation.jsx
import { useStore } from "../../store.js";

export function Consolidation() {
  const logs = useStore((s) => s.logs);
  const scouts = useStore((s) => s.scouts);
  // Two separate selectors — logs and scouts update independently; subscribing
  // to both individually avoids unnecessary re-renders from unrelated state changes.
  const scoutCount = scouts.length;

  return (
    <div class="phase-inner">
      <p class="phase-status">Writing project specification...</p>
      <div class="summary-list">
        {/* context extraction is always complete by the time consolidation runs */}
        <div class="summary-item">
          <span class="icon-done">✓</span>
          <span>Context extracted from conversation</span>
        </div>
        {scoutCount > 0 && (
          <div class="summary-item">
            <span class="icon-done">✓</span>
            <span>
              {scoutCount} scout{scoutCount !== 1 ? "s" : ""} explored the
              codebase
            </span>
          </div>
        )}
        <div class="summary-item">
          <span class="icon-pending">◌</span>
          <span>Writing decisions.md...</span>
        </div>
      </div>
      {logs.length > 0 && (
        // Last 3 log lines — same slice as renderConsolidation()
        <div class="activity-feed" style={{ marginTop: "16px" }}>
          {logs.slice(-3).map((line, i) => (
            <div key={i} class="activity-line">
              <span class="activity-tool">{line.tool}</span>
              <span>{line.summary || ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 7.16 Execution — story execution screen

```jsx
// components/phases/Execution.jsx
import { useStore } from "../../store.js";

export function Execution({ phase }) {
  const stories = useStore((s) => s.stories);

  const phaseLabel =
    phase === "decomposition"
      ? "Decomposing into stories..."
      : phase === "review"
        ? "Awaiting spec review..."
        : phase === "executing"
          ? "Executing stories..."
          : `Phase: ${phase}`;

  return (
    <div class="phase-inner">
      <p class="phase-status">{phaseLabel}</p>
      {stories.length > 0 && (
        <div class="summary-list">
          {stories.map((story) => {
            // Active statuses get a filled bullet; terminal statuses get checkmark or dash
            const icon =
              story.status === "done"
                ? "✓"
                : story.status === "skipped"
                  ? "—"
                  : story.status === "executing" ||
                      story.status === "planning" ||
                      story.status === "verifying"
                    ? "●"
                    : "◌";
            const iconCls =
              story.status === "done" ? "icon-done" : "icon-pending";
            return (
              <div key={story.storyId} class="summary-item">
                <span class={iconCls}>{icon}</span>
                <span>{story.storyId}</span>
                <span class="review-story-title"> [{story.status}]</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

### 7.17 QuestionCard — single question with option selection

```jsx
// components/forms/QuestionCard.jsx
import { useState } from "preact/hooks";

export function QuestionCard({ question, index, total, selection, onSelect }) {
  // Local state for selection and the free-text "Other" field —
  // ephemeral UI interaction, not global concern.
  const [selectedIndexes, setSelectedIndexes] = useState(() => new Set());
  const [otherInput, setOtherInput] = useState("");

  const options = question.options || [];
  const allOptions = options.map((o) => o.label);
  // "Other (type your own)" is detected by exact label match, same as forms.js
  const otherIndex = allOptions.findIndex((l) => l === "Other (type your own)");

  function buildSelection(indexes, otherVal) {
    if (question.multi) {
      const selectedOptions = [];
      let customInput;
      for (const idx of indexes) {
        if (idx === otherIndex) {
          const val = otherVal.trim();
          if (val) customInput = val;
        } else {
          selectedOptions.push(allOptions[idx]);
        }
      }
      return customInput !== undefined
        ? { selectedOptions, customInput }
        : { selectedOptions };
    } else {
      const idx = [...indexes][0];
      if (idx === otherIndex) {
        const val = otherVal.trim();
        return val ? { selectedOptions: [], customInput: val } : null;
      }
      return { selectedOptions: [allOptions[idx]] };
    }
  }

  function handleSelect(i) {
    let next;
    if (question.multi) {
      // Toggle in multi-select
      next = new Set(selectedIndexes);
      if (next.has(i)) next.delete(i);
      else next.add(i);
    } else {
      // Replace in single-select
      next = new Set([i]);
    }
    setSelectedIndexes(next);
    onSelect(buildSelection(next, otherInput));
  }

  function handleOtherInput(e) {
    const val = e.target.value;
    setOtherInput(val);
    // Re-report selection with updated free-text whenever the input changes
    if (selectedIndexes.has(otherIndex)) {
      onSelect(buildSelection(selectedIndexes, val));
    }
  }

  const showOtherInput = otherIndex !== -1 && selectedIndexes.has(otherIndex);

  return (
    <div class="question-card">
      <div class="question-header">
        {index + 1}/{total} · {question.id}
      </div>
      {question.multi && (
        <div class="question-multi-hint">select all that apply</div>
      )}
      <div class="question-text">{question.question}</div>
      <div class="options-list">
        {allOptions.map((label, i) => {
          const isSelected = selectedIndexes.has(i);
          // recommended badge shown on default option, but never on the Other option
          const isRecommended = i === question.recommended && i !== otherIndex;
          return (
            <div
              key={i}
              class={`option${i === otherIndex ? " option-other" : ""}${isSelected ? " selected" : ""}`}
              onClick={() => handleSelect(i)}
            >
              <span class={question.multi ? "checkbox-dot" : "radio-dot"} />
              <span class="option-text">{label}</span>
              {isRecommended && (
                <span class="recommended-badge">recommended</span>
              )}
            </div>
          );
        })}
        {/* other-input is always in the DOM; visible class controls display */}
        <input
          class={`other-input${showOtherInput ? " visible" : ""}`}
          type="text"
          placeholder="Type your answer..."
          value={otherInput}
          onInput={handleOtherInput}
        />
      </div>
    </div>
  );
}
```

### 7.18 AgentRow — single agent table row

```jsx
// components/AgentRow.jsx
import { shortenModel, formatTokens } from "../lib/utils.js";

export function AgentRow({ agent }) {
  const statusSymbol =
    agent.status === "running" ? "●" : agent.status === "completed" ? "✓" : "✗";
  const statusCls =
    agent.status === "running"
      ? "agent-status-running"
      : agent.status === "completed"
        ? "agent-status-done"
        : "agent-status-failed";
  const nameCls =
    agent.status === "running"
      ? "agent-name-running"
      : agent.status === "completed"
        ? "agent-name-done"
        : "agent-name-failed";

  const actions = agent.recentActions || [];
  // Show up to 5 stacked recent actions with agent-doing-lines/agent-doing-line
  // CSS classes — preserves the scrolling action trail from the current table.js.
  // Last line is highlighted via .agent-doing-line:last-child CSS rule.
  const start = Math.max(0, actions.length - 5);

  return (
    <tr>
      <td class={`col-status ${statusCls}`}>{statusSymbol}</td>
      <td class={nameCls}>{agent.name || agent.id}</td>
      <td class="col-model agent-model-cell">{shortenModel(agent.model)}</td>
      <td class="col-parent agent-parent-cell">{agent.parent || "—"}</td>
      <td class="col-tokens agent-tokens-cell">
        {formatTokens(agent.tokensSent || 0)}
      </td>
      <td class="col-tokens agent-tokens-cell">
        {formatTokens(agent.tokensReceived || 0)}
      </td>
      <td class="col-doing">
        {actions.length > 0 ? (
          <div class="agent-doing-lines">
            {actions.slice(start).map((action, i) => (
              <div key={i} class="agent-doing-line">
                {action}
              </div>
            ))}
          </div>
        ) : agent.status === "running" ? (
          <span class="agent-doing-line">initializing...</span>
        ) : null}
      </td>
    </tr>
  );
}
```

---

## 8. Migration Sequence

The rewrite is a clean swap — there is no incremental migration path because
the current code is imperative DOM manipulation that operates on hard-coded
element IDs (`#phase-content`, `#agent-tbody`, `#pill-strip`). These IDs are
shared global mutable state; there is no component boundary to isolate and
replace piecemeal. The steps are ordered to maintain a working build at each
commit.

### Step 1: Add build tooling

- Install `esbuild`, `preact`, `zustand` as devDependencies.
- Add `build:web` script to `package.json`.
- Add `src/planner/web/dist/` to `.gitignore` (note: the existing `dist/`
  pattern already covers this, but an explicit entry is clearer).
- Wire `build:web` into the existing `build` script (run before tsc).
- Add `ensureBundle()` to `server.ts` (§3.3) — this is the primary mechanism;
  the npm script is a secondary path for CI/tests.

### Step 2: Write store + SSE

- Create `js/store.js` and `js/sse.js`.
- Create `js/lib/utils.js` (copy pure functions from old `utils.js`).
- Create `js/lib/api.js` (extract `submitAnswers`, `submitReview` fetch calls).

### Step 3: Write components

- Create all component files from §6.2 file layout.
- Create `js/app.jsx` entry point.
- Verify build with `npm run build:web`.

### Step 4: Swap serving layer

- Add `ensureBundle()` function and move `STATIC_ASSETS` inside
  `startWebServer()` (§3.3).
- Update `STATIC_ASSETS` to serve `dist/app.js` instead of individual JS files.
- Add `intake-progress` event to `server.ts`: buffered state, emission in
  `startAgentPolling()` and `pushPhase()`, replay in `replayState()` (§3.4).
- Update `index.html` to use single `<div id="app">` + module script.
- Remove old JS files: `app.js`, `render.js`, `forms.js`, `table.js`,
  `utils.js` from `js/`.

### Step 5: Verify and clean up

- Full build: `npm run build:web && npm run build`.
- Manual test: run koan pipeline, verify no flash, verify all phases render,
  verify question form and review form work, verify agent table updates.
- Remove any dead code.

---

## 9. Dependency Rationale

| Package         | Size (bundled)   | Purpose                                                                                                                                          |
| --------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `preact`        | ~3KB gzip (core) | VDOM diffing, JSX components. React API in 3KB.                                                                                                  |
| `preact/compat` | ~5KB gzip        | React compatibility layer — required because zustand v4 imports from `react`. Aliased via esbuild `--alias:react=preact/compat`.                 |
| `zustand`       | ~1KB gzip        | Centralized store with selector subscriptions. Pinned to v4 — v5 imports React at module level, incompatible with Preact without a compat layer. |
| `esbuild`       | native binary    | JSX→JS bundling. Sub-100ms builds. Dev-only.                                                                                                     |

Total client-side bundle: ~16KB gzip (44KB raw). The `preact/compat` shim and
`use-sync-external-store` polyfill account for ~8KB of the overhead. To reduce
to ~8KB gzip: replace `import { create } from 'zustand'` with
`import { createStore } from 'zustand/vanilla'` and write a custom `useStore`
hook using `preact/hooks` — eliminates the React compat layer entirely.

Alternatives considered:

- **SolidJS**: Closer to re-frame's signal model, but smaller ecosystem and
  less familiar JSX semantics (no re-render, different mental model for
  conditional rendering).
- **Vanilla + DOM patching**: Would avoid dependencies but requires hand-rolling
  what Preact gives for free. More code, more bugs, same result.
- **React**: Same API as Preact but 10× larger. No benefit for this use case.

---

## 10. What This Fixes

The flash disappears because:

1. **Selective re-rendering**: Each component subscribes to its own state
   slice via `useStore(s => s.X)`. An `agents` event only re-renders
   `AgentMonitor`. Scout cards, phase content, and the header are untouched.

2. **VDOM diffing**: When a component does re-render, Preact diffs the new
   virtual DOM against the current real DOM and patches only changed nodes.
   The DOM is never torn down and rebuilt.

3. **Keyed lists**: `scouts.map(s => <ScoutCard key={s.id} .../>)` gives
   Preact stable identity for list items. Adding/removing a scout patches
   one DOM node, not the entire list.

4. **No `clearEl()`**: The concept doesn't exist. Components return what they
   want to render; Preact figures out what changed.

---

## 11. Gotchas / Implementation Notes

1. **`class` not `className`**: Preact uses standard HTML attribute names.
   Unlike React, `class` is correct in JSX. `className` works too (Preact
   accepts both) but `class` is idiomatic and matches the existing CSS.

2. **Hook import path**: Always `import { useState, useEffect, … } from 'preact/hooks'`,
   not from `'preact'`. Importing hooks from the wrong path gives a silent
   undefined and cryptic runtime errors.

3. **`render` import**: `import { render } from 'preact'` — not `preact/compat`.
   `preact/compat` is only needed when bridging React libraries; this project
   uses no React-ecosystem packages.

4. **Fragment syntax**: `<>…</>` requires `--jsx=automatic`. With the classic
   transform you'd need `import { Fragment } from 'preact'` and `<Fragment>`.
   The build command uses `--jsx=automatic` — fragments just work.

5. **Zustand shallow merge**: `setState({ agents: newArray })` merges the top
   level only. Nested object mutations (e.g. `pendingInput.payload`) are not
   detected. Always replace the whole slice: `setState({ pendingInput: { …newValue } })`.

6. **`useStore.setState` vs `set`**: The `set` function inside `create((set) => …)`
   is a closure only accessible during store initialisation. Everywhere else
   (SSE handlers, `useEffect` callbacks, event handlers) use the static
   `useStore.setState`. They are functionally equivalent; the static form is
   just the external API.

7. **`ensureBundle()` handles missing/stale bundles**: The `ensureBundle()`
   function in `server.ts` builds the bundle on-demand if `dist/app.js` is
   missing or older than any source file in `js/`. No manual `npm run build:web`
   is needed during development. The npm script is a secondary path for CI/tests.
   Note: `STATIC_ASSETS` must be populated **after** `ensureBundle()` completes,
   so the map construction moves inside `startWebServer()` (it was at module
   init scope in the old code).

8. **esbuild does not type-check**: `npm run build:web` succeeds even with
   TypeScript errors in JSX files. Run `tsc --noEmit` (the existing `check`
   script) separately if type safety on the client side matters.

9. **No `DOMContentLoaded` needed**: `<script type="module">` is deferred by
   the HTML spec — it executes after the document is parsed. Remove any
   `document.addEventListener('DOMContentLoaded', …)` wrappers from `app.jsx`.

10. **SSE reconnect replay**: The server's `replayState()` sends all current
    state on reconnect. The Zustand store will receive these as fresh `setState`
    calls — components will re-render with replayed state, which is correct.
    No special reconnect handling needed in the client.
