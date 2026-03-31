# Frontend Port: React + Zustand + Vite

## Summary

Port the koan frontend from server-rendered Jinja2 fragments + vanilla JS to a React SPA with Zustand state management and Vite build tooling. The Python backend becomes a pure JSON API + SSE server. No Node.js server in production — Python serves the built bundle.

## Decisions & Rationale

### Zustand over Effector or Redux Toolkit

The author has re-frame/reagent (ClojureScript) experience and wanted the closest minimal equivalent in the React ecosystem. Re-frame's core value is: a single app-db atom, pure event handlers that transform it, and subscriptions as reactive derived queries.

Zustand covers this model without the ceremony:

- Single store = `app-db`
- Action functions inside the store = event handlers
- Selector functions = subscriptions

Effector would have been architecturally closer (explicit events, stores, effects as first-class objects), but its smaller community and steeper onboarding cost outweigh the purity benefit for a project this size. Redux Toolkit has the ecosystem but too much boilerplate. Zustand is the pragmatic middle ground.

### Vite over Next.js or Remix

koan is a local developer tool, not a public website. Server-side rendering provides no value: there are no SEO requirements, no cold-load performance targets, and only one operator runs the app at a time. Vite gives fast HMR during development and a clean static bundle for production with zero SSR complexity.

### No router library

The app has exactly two views: the landing configuration page and the live run view. The transition between them is driven by a single boolean (`runStarted`) in the store. A routing library (React Router, TanStack Router) would add a dependency, route definitions, and navigation primitives for a problem that a conditional render solves in three lines.

### Python serves built assets in production

No Node.js process in production. The Starlette server already handles HTTP; it can serve `frontend/dist/` as static files via a `StaticFiles` mount. This keeps the deployment model identical to the current one: one `uv run koan` command, one port, no additional infrastructure.

### Server-rendered HTML fragments → JSON SSE

This is the fundamental architectural shift. The current system has Python render Jinja2 templates to HTML strings, push them over SSE, and the browser does `innerHTML` swaps. This couples every UI change to both Python templates and JS event handlers, and causes a class of silent bugs where DOM element IDs are destroyed mid-stream.

The new system: `push_sse()` emits raw JSON. React components subscribe to store slices. The browser renders from data, not from server-generated markup. `_render_fragment()` is deleted entirely.

### CSS design system ports directly

The existing stylesheet uses CSS custom properties (`--color-bg`, `--text-primary`, etc.) with no preprocessor and no framework. It is framework-agnostic by construction. The four CSS files (`variables.css`, `layout.css`, `components.css`, `animations.css`) can be imported into the React app without modification. In the frontend directory they are consolidated to three files — `animations.css` content is merged into `components.css` since they are co-dependent (animation classes are applied by component class names).

### Minimal dependencies

React 19, Zustand 5, Vite 6. No axios (native `fetch` is sufficient), no react-router (see above), no CSS-in-JS (existing CSS ports directly), no component library (existing design system is the component library). Every added dependency is a future maintenance burden; this list is the minimum viable set.

---

## Motivation

The current architecture (server renders HTML fragments, pushes via SSE, JS does `innerHTML` swap) has hit its limits:

- **Fragile DOM updates**: `outerHTML` vs `innerHTML` bugs silently break SSE event handlers when target element IDs are destroyed. This caused multiple regressions during the initial bug-fix session.
- **No component state**: The activity feed can't auto-scroll reliably, "thinking" indicators don't flow downward as new entries arrive, elapsed timers require manual `setInterval` hacks scanning the DOM for `[data-started-at]` attributes.
- **Server-side coupling**: Every UI change requires modifying both a Python Jinja2 template and the corresponding JS event handler. There is no single source of truth for what a UI element looks like.
- **No animations**: Fragment swapping (`innerHTML = serverHTML`) makes CSS transitions and entry animations impossible — the DOM node is replaced wholesale each time.

## Architecture

### Directory Layout

```
koan/
├── koan/                     # Python package (existing, mostly unchanged)
│   ├── driver.py             # simplified: push_sse sends JSON only, _render_fragment() deleted
│   ├── web/
│   │   ├── app.py            # API routes only; no Jinja2 rendering for SSE events
│   │   ├── mcp_endpoint.py   # unchanged — subagent communication is backend-only
│   │   └── static/
│   │       └── app/          # Vite build output (vite build --outDir ../koan/web/static/app)
│   └── ...
├── frontend/                 # NEW — lives alongside koan/, not inside it
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts        # proxies /api/*, /events, /mcp/* to Python in dev
│   ├── index.html            # Vite entry point; references /src/main.tsx
│   ├── src/
│   │   ├── main.tsx          # mounts <App /> into #root; imports global CSS
│   │   ├── App.tsx           # top-level layout; owns SSE connection lifecycle
│   │   ├── store/
│   │   │   ├── index.ts      # single Zustand store — the app-db equivalent
│   │   │   └── selectors.ts  # derived state computed from store slices
│   │   ├── sse/
│   │   │   └── connect.ts    # EventSource wrapper: reconnect logic + store dispatch
│   │   ├── api/
│   │   │   └── client.ts     # typed fetch wrappers for all POST/PUT endpoints
│   │   ├── components/
│   │   │   ├── Header.tsx
│   │   │   ├── PillStrip.tsx
│   │   │   ├── StatusSidebar.tsx
│   │   │   ├── ActivityFeed.tsx
│   │   │   ├── AgentMonitor.tsx
│   │   │   ├── ArtifactsSidebar.tsx
│   │   │   ├── Notification.tsx          # toast notifications from 'notification' SSE events
│   │   │   ├── interactions/
│   │   │   │   ├── AskWizard.tsx         # multi-question card navigation
│   │   │   │   ├── ArtifactReview.tsx
│   │   │   │   └── WorkflowDecision.tsx  # chat-style phase selection
│   │   │   ├── Completion.tsx
│   │   │   ├── LandingPage.tsx
│   │   │   └── SettingsOverlay.tsx
│   │   ├── hooks/
│   │   │   ├── useElapsed.ts     # replaces manual setInterval + DOM attribute scanning
│   │   │   └── useAutoScroll.ts  # replaces manual scrollTop manipulation
│   │   └── styles/
│   │       ├── variables.css     # ported verbatim from koan/web/static/css/variables.css
│   │       ├── layout.css        # ported verbatim
│   │       └── components.css    # ported from components.css + animations.css merged in
│   └── dist/                 # Vite build output (gitignored)
└── pyproject.toml
```

### Dev vs Production

**Development:** Vite dev server proxies all backend traffic to the running Python process. SSE requires special proxy configuration — see `vite.config.ts` below.

```
vite dev (:5173)  →  proxy /api/*, /events, /mcp/*  →  python (:8000)
```

**Production:** A single `uv run koan` command. Python serves the compiled bundle as static files. No Node.js process required.

```
python (:8000)  →  /static/app/*         →  serves frontend/dist/ (Vite build output)
                →  /api/*, /events, /mcp/*  →  existing routes (unchanged)
                →  /* (all other paths)  →  serves index.html (SPA fallback, must be last)
```

**`vite.config.ts`:**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],

  // In production the built assets live at /static/app/ on the Python server.
  // This must match the StaticFiles mount path in create_app().
  base: "/static/app/",

  build: {
    // Output directly into the Python package's static directory so
    // `uv run koan` serves the latest build without a copy step.
    outDir: "../koan/web/static/app",
    emptyOutDir: true,
  },

  server: {
    proxy: {
      // Proxy all backend traffic through Vite's dev server.
      // The SSE endpoint (/events) needs special handling: disable buffering
      // so chunks are forwarded immediately rather than batched. Without this,
      // SSE events arrive in groups after a delay, breaking the real-time feed.
      "/events": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Disable response buffering for the SSE stream.
        // http-proxy buffers responses by default; the proxyRes hook
        // forwards streaming headers so chunks arrive immediately.
        // Without this, SSE events batch and the real-time feed breaks.
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("Accept", "text/event-stream");
          });
          proxy.on("proxyRes", (proxyRes) => {
            // Prevent any intermediate buffering (nginx, proxies, etc.)
            proxyRes.headers["x-accel-buffering"] = "no";
            proxyRes.headers["cache-control"] = "no-cache";
          });
        },
      },
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/mcp": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
```

> **Verify SSE during Phase 3:** Before building any components that consume streaming data, confirm that SSE events arrive incrementally in the Vite dev proxy. Open the browser DevTools Network tab, inspect the `/events` connection, and confirm events appear one-by-one rather than in batches.

**Starlette route order in `create_app()`:**

Route order is significant in Starlette — first match wins. The SPA fallback must come last.

```python
routes = [
    # MCP before static, in case path overlap ever occurs
    Mount("/mcp", app=mcp_app),
    # API routes (all /api/* handlers)
    Route("/api/start-run", api_start_run, methods=["POST"]),
    # ... all other /api/* routes ...
    # SSE stream
    Route("/events", sse_stream),
    # Built React app assets — served from frontend/dist/ (= koan/web/static/app/)
    Mount("/static/app", app=StaticFiles(directory=FRONTEND_DIST, html=False)),
    # Legacy static (if any other static assets remain)
    Mount("/static", app=StaticFiles(directory=STATIC_DIR)),
    # SPA fallback: any path not matched above returns index.html.
    # React reads store state (runStarted) to decide which view to render.
    Route("/{path:path}", spa_fallback),
]
```

Where `FRONTEND_DIST = Path(__file__).parent / "static" / "app"`.

## Zustand Store

Single store modeling the complete UI state. Every piece of state the current `AppState` exposes to the frontend lives here. Actions (mutations) are defined inline following Zustand's standard pattern — this is the re-frame `reg-event-db` equivalent, without a separate dispatch call.

```ts
// AgentInfo: shape returned by _build_subagent_json / _build_agents_json.
// All time/token values are raw numbers — formatting is done in components
// via useElapsed and formatTokens helpers, not on the Python side.
interface AgentInfo {
  agentId: string;
  role: string;
  model: string | null;
  step: number;
  stepName: string; // resolved from phase_module.STEP_NAMES server-side;
  // e.g. "Extract" not "step 1". Must be in the SSE payload.
  startedAt: number; // UTC epoch milliseconds (from datetime.now(timezone.utc))
  tokensSent: number; // raw count; formatted by formatTokens() in the component
  tokensReceived: number;
}

// Shape of artifacts from _build_artifacts_json. Flat list;
// grouped into a directory tree by the useArtifactTree selector.
interface ArtifactFile {
  path: string; // relative to epic dir, e.g. "brief/overview.md"
  size: number; // bytes
  modifiedAt: number; // UTC epoch milliseconds
}

// Shape of pipeline-end SSE event payload.
interface CompletionInfo {
  success: boolean;
  summary: string; // LLM-generated run summary (empty on failure)
  error: string; // error message (empty on success)
  phase: string; // phase that was active when pipeline ended
  artifacts: ArtifactFile[];
}

// Notification entry with mapped severity for styling.
interface NotificationEntry {
  id: string; // crypto.randomUUID() — unique per notification
  type: string; // original categorical type from backend (e.g. 'runner_error')
  severity: "error" | "warning" | "info"; // mapped at the SSE bridge boundary
  message: string;
  detail?: string;
}

interface KoanState {
  // ── Connection ──────────────────────────────────────────────────────────────
  // Tracks SSE health. Components can show a disconnected banner when false.
  connected: boolean;

  // ── Run state ───────────────────────────────────────────────────────────────
  // runStarted gates which top-level view renders (landing vs live).
  // Avoids a router dependency for a binary choice.
  runStarted: boolean;
  phase: string; // current pipeline phase name, e.g. "intake"
  donePhases: string[]; // phases completed; drives pill strip styling

  // ── Primary agent ────────────────────────────────────────────────────────────
  // The phase-level agent (intake, brief-writer, etc.) shown in the left sidebar.
  // Null when no agent is active (between phases or before run starts).
  primaryAgent: AgentInfo | null;

  // ── Intake sub-phase progress ────────────────────────────────────────────────
  // Set by 'intake-progress' SSE events during the intake phase only.
  // Null outside of intake; StatusSidebar renders this when non-null.
  intakeProgress: {
    subPhase: string;
    confidence: string | null;
    summary: string;
  } | null;

  // ── Scout agents ─────────────────────────────────────────────────────────────
  // Parallel sub-agents spawned by koan_request_scouts. Keyed by agent_id.
  // The 'agents' SSE event delivers a full replacement list — there are no
  // per-scout incremental update events. setScouts does a wholesale replace.
  scouts: Record<string, AgentInfo>;

  // ── Activity feed ────────────────────────────────────────────────────────────
  // activityLog is append-only — entries are never removed.
  // streamBuffer accumulates token-delta events; rendered as the in-flight
  // streaming text until cleared by a 'token-clear' event.
  activityLog: ActivityEntry[];
  streamBuffer: string;

  // ── Notifications ────────────────────────────────────────────────────────────
  // Transient toasts rendered by Notification.tsx. Each entry auto-dismisses.
  // The 'notification' SSE event carries type, message, and optional metadata.
  notifications: NotificationEntry[];

  // ── Interaction ──────────────────────────────────────────────────────────────
  // Only one interaction is active at a time (enforced by the backend queue).
  // Setting this to non-null causes the workspace to render the interaction UI
  // instead of the activity feed. null when the interaction is cleared.
  // type: 'ask' | 'artifact-review' | 'workflow-decision'
  activeInteraction: Interaction | null;

  // ── Artifacts ────────────────────────────────────────────────────────────────
  // Flat list; grouped into a tree by the useArtifactTree selector.
  artifacts: ArtifactFile[];

  // ── Pipeline completion ──────────────────────────────────────────────────────
  // Set once on pipeline-end SSE event; triggers Completion view.
  completion: CompletionInfo | null;

  // ── Settings ─────────────────────────────────────────────────────────────────
  // Settings overlay is fully client-side; open/close state lives here.
  // profiles and installations are fetched from /api/* when the overlay opens.
  settingsOpen: boolean;
  profiles: Profile[];
  installations: Installation[];

  // ── Actions ──────────────────────────────────────────────────────────────────
  setConnected: (v: boolean) => void;
  setPhase: (phase: string) => void; // also sets runStarted=true and derives donePhases
  setPrimaryAgent: (agent: AgentInfo | null) => void;
  setIntakeProgress: (p: KoanState["intakeProgress"]) => void;
  setScouts: (scouts: Record<string, AgentInfo>) => void; // full replace
  appendLog: (entry: ActivityEntry) => void;
  appendStreamDelta: (delta: string) => void;
  clearStream: () => void; // called on 'token-clear' SSE event
  addNotification: (n: NotificationEntry) => void;
  dismissNotification: (id: string) => void;
  setInteraction: (interaction: Interaction | null) => void;
  setArtifacts: (artifacts: ArtifactFile[]) => void;
  setCompletion: (info: CompletionInfo) => void;
}
```

### Selectors

Selectors are the re-frame `reg-sub` equivalent. Zustand re-renders only the component whose subscribed slice changed. Keep selectors close to the components that use them, or in `selectors.ts` if shared.

```ts
// useStore(selector) is Zustand's subscription primitive.
// Each hook subscribes only to the slice it reads; unrelated state changes
// do not trigger re-renders in components using these hooks.

// Transforms scouts dict → array for rendering in AgentMonitor table rows.
const useScoutList = () => useStore((s) => Object.values(s.scouts));

// Isolated subscription: StatusSidebar re-renders only when primaryAgent changes.
const usePrimaryAgent = () => useStore((s) => s.primaryAgent);

// Boolean subscription: drives conditional rendering of the interaction overlay
// without subscribing to the full interaction payload.
const useHasInteraction = () => useStore((s) => s.activeInteraction !== null);

// Derived computation: groups flat artifact list into {dir: files[]} tree.
// If this selector is expensive, wrap in useMemo inside the component.
const useArtifactTree = () => useStore((s) => groupByDirectory(s.artifacts));
```

## SSE Bridge

The SSE connection is the sole ingress path for live state. All backend events flow through this bridge; nothing else writes to the store from outside the component tree. The `connectSSE` function is called from an `App.tsx` `useEffect` which owns reconnect scheduling.

```ts
// connectSSE opens an EventSource and wires every SSE event type to a store action.
// Returns the EventSource so the caller can close it on unmount or reconnect.
// Does NOT schedule its own reconnect — App.tsx owns that lifecycle.
function connectSSE(store: KoanStore): EventSource {
  const es = new EventSource("/events");

  store.getState().setConnected(true);

  // ── Structural events ────────────────────────────────────────────────────────
  // These correspond to the low-frequency events that previously triggered
  // server-rendered HTML fragment swaps. Now they're just data — the store
  // updates and React re-renders the relevant component slice.

  es.addEventListener("phase", (e) => {
    const d = JSON.parse(e.data);
    // setPhase also sets runStarted=true (any phase event means a run is active)
    // and derives donePhases (all known phases before current). This is critical
    // for page reloads mid-run: the replayed 'phase' event flips runStarted,
    // so the user sees the live view instead of the landing page.
    store.getState().setPhase(d.phase);
  });

  es.addEventListener("subagent", (e) => {
    const d = JSON.parse(e.data);
    // _build_subagent_json returns {"agent_id": None} when no primary agent is active.
    // Guard against this to avoid setting primaryAgent to an object with all-undefined
    // fields — StatusSidebar checks for null to show the idle state.
    if (d.agent_id === null || d.agent_id === undefined) {
      store.getState().setPrimaryAgent(null);
      return;
    }
    // started_at_ms is a UTC epoch ms timestamp (Python: datetime.now(timezone.utc)).
    // The useElapsed hook computes display string client-side on a 1s interval,
    // eliminating the DOM-scanning setInterval hack from koan.js.
    // stepName is resolved server-side from phase_module.STEP_NAMES — the client
    // does not have access to step name mappings.
    store.getState().setPrimaryAgent({
      agentId: d.agent_id,
      role: d.role,
      model: d.model,
      step: d.step,
      stepName: d.step_name,
      startedAt: d.started_at_ms,
      tokensSent: d.tokens_sent,
      tokensReceived: d.tokens_received,
    });
  });

  es.addEventListener("subagent-idle", () => {
    // Agent process exited; clear the sidebar until the next agent spawns.
    store.getState().setPrimaryAgent(null);
  });

  es.addEventListener("agents", (e) => {
    const d = JSON.parse(e.data);
    // d.agents is an array from _build_agents_json(). Python emits snake_case;
    // we map to camelCase here at the bridge boundary — same as the subagent handler.
    // Without this mapping, Object.fromEntries would key everything under "undefined"
    // because a.agentId doesn't exist on the raw JSON (it's a.agent_id).
    const scouts = Object.fromEntries(
      d.agents.map((a: any) => [
        a.agent_id,
        {
          agentId: a.agent_id,
          role: a.role,
          model: a.model,
          step: a.step,
          stepName: a.step_name,
          startedAt: a.started_at_ms,
          tokensSent: a.tokens_sent,
          tokensReceived: a.tokens_received,
        } satisfies AgentInfo,
      ]),
    );
    store.getState().setScouts(scouts);
  });

  es.addEventListener("artifacts", (e) => {
    const d = JSON.parse(e.data);
    store.getState().setArtifacts(d.artifacts);
  });

  es.addEventListener("intake-progress", (e) => {
    const d = JSON.parse(e.data);
    // Only emitted during the intake phase. StatusSidebar renders subPhase
    // and summary when this is non-null.
    store.getState().setIntakeProgress({
      subPhase: d.subPhase ?? "",
      confidence: d.confidence ?? null,
      summary: d.summary ?? "",
    });
  });

  // ── High-frequency events ────────────────────────────────────────────────────
  // These bypass the store's full update cycle by targeting append-only slices.
  // token-delta can fire many times per second during streaming.

  es.addEventListener("token-delta", (e) => {
    const d = JSON.parse(e.data);
    store.getState().appendStreamDelta(d.delta);
  });

  es.addEventListener("token-clear", () => {
    // Emitted when the backend resets the stream for a new turn.
    // Clears streamBuffer so the next turn starts fresh.
    store.getState().clearStream();
  });

  es.addEventListener("logs", (e) => {
    const d = JSON.parse(e.data);
    // ActivityEntry shape: { tool: string, summary: string, inFlight: boolean, ts?: string }
    // ActivityFeed renders inFlight entries with a pulse animation and settles
    // them when a matching non-inFlight entry for the same tool arrives.
    store.getState().appendLog(d.line);
  });

  // ── Notifications ────────────────────────────────────────────────────────────
  es.addEventListener("notification", (e) => {
    const d = JSON.parse(e.data);
    // Transient toasts: runner errors, config warnings, cancelled interactions.
    // Notification.tsx auto-dismisses after a timeout.
    // Backend notification types are categorical event names (e.g. 'runner_error',
    // 'bootstrap_failure', 'interaction_cancelled'), NOT severity levels.
    // Map to severity here at the bridge boundary for Notification.tsx styling.
    const SEVERITY_MAP: Record<string, "error" | "warning" | "info"> = {
      runner_error: "error",
      bootstrap_failure: "error",
      spawn_failure: "error",
      interaction_cancelled: "info",
      config_warning: "warning",
    };
    store.getState().addNotification({
      id: crypto.randomUUID(),
      type: d.type, // original categorical type
      severity: SEVERITY_MAP[d.type] ?? "info", // mapped severity for styling
      message: d.message,
      detail: d.details,
    });
  });

  // ── Interactions ─────────────────────────────────────────────────────────────
  // The backend enqueues at most one interaction at a time. Setting activeInteraction
  // non-null causes App.tsx to render the interaction component over the activity feed.

  es.addEventListener("interaction", (e) => {
    const d = JSON.parse(e.data);
    // 'cleared' means the interaction was resolved; restore the activity feed.
    store.getState().setInteraction(d.type === "cleared" ? null : d);
  });

  es.addEventListener("pipeline-end", (e) => {
    const d = JSON.parse(e.data);
    store.getState().setCompletion(d);
  });

  // ── Error handling ───────────────────────────────────────────────────────────
  // EventSource fires onerror on network failure AND on clean server close.
  // We close and signal the caller; App.tsx schedules the reconnect.
  es.onerror = () => {
    store.getState().setConnected(false);
    es.close();
    // onDisconnect is a callback passed by App.tsx to trigger reconnect scheduling.
    // This keeps the exponential backoff logic in one place (App.tsx useEffect).
  };

  return es;
}
```

**`App.tsx` reconnect loop:**

```ts
useEffect(() => {
  let es: EventSource | null = null;
  let retryDelay = 500;

  function connect() {
    es = connectSSE(store);
    // Override the onerror set inside connectSSE to schedule our retry.
    es.onerror = () => {
      store.getState().setConnected(false);
      es?.close();
      // Exponential backoff capped at 5s, matching the old koan.js behaviour.
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 5000);
    };
    // Reset backoff on successful connection.
    es.onopen = () => {
      retryDelay = 500;
    };
  }

  connect();

  // Cleanup on unmount — prevents duplicate SSE connections in React StrictMode.
  return () => {
    es?.close();
  };
}, []); // Empty dep array: connect once, reconnect is managed inside
```

## Backend Changes

### Remove from Python

1. **Delete `_render_fragment()`** from `driver.py` — the 120-line Jinja2 dispatch function that couples the driver to the web layer
2. **Delete all fragment templates** — `koan/web/templates/fragments/*.html` (13 files, ~350 lines)
3. **Delete `koan.js`** — replaced entirely by the React app
4. **Delete `base.html`, `live.html`, `landing.html`** — replaced by `frontend/index.html` + React
5. **Remove `jinja2` dependency** from `pyproject.toml` once no templates remain

### Modify in Python

**`push_sse()` — emit raw JSON, no HTML wrapping:**

The key change: `push_sse` previously called `_render_fragment()` which rendered Jinja2 and returned `{html, target, ...data}`. Now it enriches the payload with current state and emits pure data. The `html` and `target` fields disappear from every SSE event.

> **Critical:** `_render_fragment()` currently has the side effect `app_state.phase = phase` inside the `phase` event branch. This is the only place `app_state.phase` is written during a run. When `_render_fragment()` is deleted, this assignment must be preserved in `push_sse()`.

```python
def push_sse(app_state, event_type, payload):
    # --- Side effects that currently live inside _render_fragment() ---
    # Must be preserved here after _render_fragment() is deleted.
    if event_type == "phase":
        # app_state.phase is read by _build_subagent_json and other helpers.
        # Without this assignment, all subsequent subagent payloads would
        # return "intake" regardless of the actual phase.
        phase = payload if isinstance(payload, str) else payload.get("phase", "")
        app_state.phase = phase
        payload = {"phase": phase}

    # --- Structural events: enrich payload with current state ---
    # These replace _render_fragment()'s template rendering — same data,
    # no HTML generation.
    elif event_type in ("subagent", "subagent-idle"):
        # subagent/subagent-idle payloads from callers are always discarded.
    # We rebuild from AppState to guarantee consistent shape.
    # Returns {"agent_id": None, ...} when no primary agent is active.
    payload = _build_subagent_json(app_state)

    elif event_type == "agents":
        # Full scout list — the frontend does a wholesale replace.
        payload = {"agents": _build_agents_json(app_state)}

    elif event_type == "artifacts":
        payload = {"artifacts": _build_artifacts_json(app_state)}

    # intake-progress: pass through payload fields (subPhase, confidence, summary).
    # No agent enrichment — agent state arrives via the separate 'subagent' event.

    elif event_type == "intake-progress":
        # Pass through subPhase/confidence/summary from caller.
        # Agent state is NOT included — it arrives via the 'subagent' SSE event.
        payload = payload if isinstance(payload, dict) else {}

    # --- Cache stateful events for replay to reconnecting clients ---
    # The replay mechanism is unchanged; only the payload format changes
    # (was {html, target, ...}, now pure data).
    if event_type in STATEFUL_EVENTS:
        app_state.last_sse_values[event_type] = payload

    for queue in app_state.sse_clients:
        queue.put_nowait((event_type, payload))
```

**New JSON builder functions** (replace `_build_subagent_display` etc.):

```python
def _build_subagent_json(app_state) -> dict:
    """Return primary agent state as a JSON-serialisable dict.

    Raw values only — no pre-formatted strings. The React client formats
    elapsed time via useElapsed() and token counts via formatTokens().
    step_name is resolved here because the client has no access to
    phase_module.STEP_NAMES.
    """
    for agent in app_state.agents.values():
        if not agent.is_primary:
            continue
        return {
            "agent_id": agent.agent_id,
            "role": agent.role,
            "model": agent.model,
            "step": agent.step,
            # Resolved server-side; falls back to "step N" if not in STEP_NAMES.
            "step_name": (
                agent.phase_module.STEP_NAMES.get(agent.step, f"step {agent.step}")
                if agent.phase_module and hasattr(agent.phase_module, "STEP_NAMES")
                else f"step {agent.step}"
            ),
            # UTC epoch milliseconds; client uses Date.now() - startedAt for elapsed.
            "started_at_ms": int(agent.started_at.timestamp() * 1000),
            # Raw counts; client formats as "12k / 4k" or similar.
            "tokens_sent": agent.token_count.get("sent", 0),
            "tokens_received": agent.token_count.get("received", 0),
        }
    return {"agent_id": None}  # no primary agent active


def _build_agents_json(app_state) -> list[dict]:
    """Return scout (non-primary) agents as a list for the monitor table.

    Same raw-values convention as _build_subagent_json.
    agent_id is included so the frontend can key the Record<string, AgentInfo>.
    """
    result = []
    for agent in app_state.agents.values():
        if agent.is_primary:
            continue
        result.append({
            "agent_id": agent.agent_id,
            "role": agent.role,
            "model": agent.model,
            "step": agent.step,
            "step_name": f"step {agent.step}",  # scouts don't have STEP_NAMES
            "started_at_ms": int(agent.started_at.timestamp() * 1000),
            "tokens_sent": agent.token_count.get("sent", 0),
            "tokens_received": agent.token_count.get("received", 0),
            "doing": f"step {agent.step}",       # for the "Doing" column
        })
    return result


def _build_artifacts_json(app_state) -> list[dict]:
    """Return artifact list as JSON-serialisable dicts.

    Flat list; the frontend groups into a directory tree via the
    useArtifactTree selector. Sizes are raw bytes (client formats).
    modifiedAt is UTC epoch milliseconds for consistency with startedAt.
    """
    if not app_state.epic_dir:
        return []
    try:
        from .artifacts import list_artifacts
        return [
            {
                "path": a["path"],
                "size": a["size"],
                "modifiedAt": int(a["modified_at"] * 1000),
            }
            for a in list_artifacts(app_state.epic_dir)
        ]
    except Exception:
        return []
```

**`landing_page()` → SPA fallback route:**

```python
# Must be registered LAST so /api/*, /mcp/*, and /static/* routes take priority.
# Starlette route ordering is significant — first match wins.
async def spa_fallback(request):
    # Return the built React app entry point for any path not matched above.
    # React reads store state (runStarted) to decide which view to render.
    return FileResponse(FRONTEND_DIST / "index.html")
```

**Convert settings endpoints to JSON:**

Three endpoints currently return server-rendered HTML fragments. Replace with JSON:

- `GET /api/settings/body` → `{profiles: [...], installations: [...], activeInstallations: {runner_type: alias}, scoutConcurrency: N}`
- `GET /api/settings/profile-form` → `{name, tiers, availableRunners, isEdit}`
- `GET /api/settings/installation-form` → `{alias, runnerType, binary, extraArgs, allRunners, isEdit}`

`SettingsOverlay.tsx` renders from these JSON responses using its own component state for form fields. The cascade dropdown logic (runner → available models → thinking modes) moves into the component using local `useState`.

### Keep Unchanged

- `mcp_endpoint.py` — subagent communication over HTTP is entirely backend-internal
- All `/api/*` JSON endpoints — already return JSON; no changes needed
- `/events` SSE transport — same EventSource protocol; payloads lose `html`/`target` fields only
- `driver.py` orchestration logic, phase modules, subagent lifecycle
- `interactions.py` queue management and `asyncio.Future` blocking pattern

## Component Mapping

| Current (Jinja2 + vanilla JS)             | New (React + Zustand)                  | Store subscription                        |
| ----------------------------------------- | -------------------------------------- | ----------------------------------------- |
| `live.html` layout                        | `App.tsx`                              | `runStarted`                              |
| `status_sidebar.html`                     | `StatusSidebar.tsx`                    | `primaryAgent`, `phase`, `intakeProgress` |
| `monitor.html`                            | `AgentMonitor.tsx`                     | `scouts` (via `useScoutList`)             |
| `artifacts_sidebar.html`                  | `ArtifactsSidebar.tsx`                 | `artifacts` (via `useArtifactTree`)       |
| `interaction_ask.html` + JS handlers      | `AskWizard.tsx`                        | `activeInteraction`                       |
| `interaction_workflow.html` + JS handlers | `WorkflowDecision.tsx`                 | `activeInteraction`                       |
| `interaction_artifact_review.html`        | `ArtifactReview.tsx`                   | `activeInteraction`                       |
| `completion.html`                         | `Completion.tsx`                       | `completion`                              |
| `landing.html`                            | `LandingPage.tsx`                      | `runStarted` (negated)                    |
| `settings_body.html` + cascade JS         | `SettingsOverlay.tsx`                  | `settingsOpen`, local state               |
| Toast notifications in `koan.js`          | `Notification.tsx`                     | `notifications`                           |
| Manual `setInterval` for elapsed          | `useElapsed(startedAt)` hook           | —                                         |
| Manual `scrollTop` management             | `useAutoScroll(ref)` hook              | —                                         |
| SSE reconnect in `koan.js`                | `sse/connect.ts` + `App.tsx` useEffect | —                                         |
| `intake-progress` SSE handler             | `StatusSidebar.tsx`                    | `intakeProgress`                          |
| `story` SSE event                         | out of scope for v1 — see note below   | —                                         |
| `frozen-logs` SSE event                   | out of scope for v1 — see note below   | —                                         |

> **`story` events:** Emitted during the execution phase with story lifecycle status (`planning`, `executing`, `verifying`, `done`, `retry`, `skipped`). Not in scope for the v1 React port — the execution phase will show only primary agent status and activity feed. **Known regression:** users lose story-level progress visibility during the longest pipeline phase. Add a `stories` store slice and a `StoryProgress` component when the execution phase UI is designed.

> **`frozen-logs` events:** Emitted once before the orchestrator subagent spawns to snapshot the current activity log. Currently handled by `koan.js` as a fragment swap. For v1, this can be ignored — the activity feed maintains its own append-only log. If the orchestrator phase needs to show a historical log boundary, add it in a follow-up.

## Migration Order

### Phase 1: Parallel Setup

- Initialize `frontend/` with Vite + React + TypeScript + Zustand
- Configure Vite proxy including SSE-specific settings (see `vite.config.ts` above)
- Port CSS files verbatim; verify design tokens render correctly in React
- Build `App.tsx` shell with three-column layout (no data yet — static skeleton)

### Phase 2: Landing Page

- `LandingPage.tsx` — task textarea, profile select, scout concurrency input, start button
- API client (`client.ts`) for `/api/start-run` and `/api/probe`
- Store: `runStarted` flag toggles landing → live view

### Phase 3: Live View Core

- SSE bridge (`connect.ts`) — connect, parse all event types, dispatch to store
- Verify SSE events arrive incrementally through the Vite proxy (not batched)
- **Dev-time constraint:** During Phases 3-5, the Python backend still emits HTML-wrapped `{html, target, ...}` payloads for structural events. The React bridge will only receive correct JSON-only payloads after Phase 6. Use mock store state (`useStore.setState({...})` in DevTools console) to drive component rendering during development.
- `StatusSidebar.tsx` — phase, primary agent, `useElapsed` hook, `intakeProgress`
- `ActivityFeed.tsx` — log entry list, `useAutoScroll` hook, thinking animation, stream buffer
- `PillStrip.tsx` — phase pills from `phase` + `donePhases`
- `Notification.tsx` — toast queue with auto-dismiss

### Phase 4: Interactions

- `AskWizard.tsx` — card-per-question navigation, radio/checkbox, "Other" text, Use Defaults
- `WorkflowDecision.tsx` — chat turns display, phase option buttons, context textarea
- `ArtifactReview.tsx` — content display, feedback textarea, Accept / Send Feedback
- API client additions: `/api/answer`, `/api/artifact-review`, `/api/workflow-decision`

### Phase 5: Remaining Views

- `AgentMonitor.tsx` — scout table rows; status icon, role, model, tokens, elapsed, doing
- `ArtifactsSidebar.tsx` — folder toggle, file list, artifact content overlay
- `SettingsOverlay.tsx` — profiles CRUD, installations CRUD, cascade dropdowns from `/api/probe`
- `Completion.tsx` — success/failure summary, artifact list

### Phase 6: Backend Cleanup

- Delete `_render_fragment()` from `driver.py` (after preserving `app_state.phase` assignment)
- Delete fragment templates and full-page Jinja2 templates
- Delete `koan.js` and old CSS from `koan/web/static/`
- Implement new JSON builder functions (`_build_subagent_json`, `_build_agents_json`, `_build_artifacts_json`)
- Convert three settings HTML endpoints to JSON
- Remove `jinja2` from `pyproject.toml`
- **Atomic route swap:** Remove `Route("/", landing_page)` and add `Route("/{path:path}", spa_fallback)` in a single commit. Starlette's `/{path:path}` does match the empty path `/`, but add a comment documenting this non-obvious behaviour. Also add `StaticFiles` mount for `frontend/dist/`
- Run full test suite; update any tests that mock rendered HTML or check for `html`/`target` fields in SSE payloads

## Dependencies

```json
{
  "dependencies": {
    // React 19 ships concurrent features and the new compiler by default.
    // react-dom is the browser renderer; separate package since React 0.14.
    "react": "^19",
    "react-dom": "^19",

    // Zustand 5 uses the React 18+ useSyncExternalStore primitive under the hood,
    // which gives correct concurrent-mode behaviour without extra configuration.
    "zustand": "^5"
  },
  "devDependencies": {
    "@types/react": "^19",
    "@types/react-dom": "^19",

    // TypeScript 5.7 required for React 19 type compatibility.
    "typescript": "^5.7",

    // Vite 6 + the React plugin handles JSX transform (no import React needed),
    // fast HMR via esbuild, and production bundling via Rollup.
    "vite": "^6",
    "@vitejs/plugin-react": "^4"
  }
}
```

Intentionally minimal. No router library (two views, conditional render). No CSS framework (existing design tokens port directly). No fetch library (native `fetch` with typed wrappers in `api/client.ts` is sufficient). No state middleware (Zustand devtools can be added if needed, but not a startup dependency).
