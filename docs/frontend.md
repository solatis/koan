# Frontend

React 19 + Zustand 5 + Vite 6 SPA. Python serves the built bundle as static
files — no Node.js in production.

> Parent doc: [architecture.md](./architecture.md)

---

## Directory Layout

```
frontend/                   # source tree (alongside koan/ Python package)
├── package.json
├── tsconfig.json
├── vite.config.ts          # proxies /api/*, /events, /mcp/* to Python in dev
├── index.html              # Vite entry point
├── src/
│   ├── main.tsx            # mounts <App /> into #root; imports global CSS
│   ├── App.tsx             # top-level layout; owns SSE connection lifecycle
│   ├── store/
│   │   ├── index.ts        # single Zustand store (the app-db equivalent)
│   │   └── selectors.ts    # derived state computed from store slices
│   ├── sse/
│   │   └── connect.ts      # EventSource wrapper: version-negotiated catch-up + fold
│   ├── api/
│   │   └── client.ts       # typed fetch wrappers for POST/PUT endpoints
│   ├── components/         # one file per UI component (see Component Mapping)
│   ├── hooks/
│   │   ├── useElapsed.ts   # elapsed time hook for agent start times
│   │   └── useAutoScroll.ts
│   └── styles/
│       ├── variables.css   # CSS custom properties
│       ├── layout.css
│       └── components.css  # components.css + animations.css merged
└── dist/                   # Vite build output (gitignored)

koan/web/static/app/        # Vite build target (committed build artifacts)
```

---

## Dev vs Production

**Development:** Vite dev server proxies all backend traffic.

```
vite (:5173)  →  /api/*, /events, /mcp/*  →  python (:8000)
```

SSE requires buffering disabled in the proxy — `vite.config.ts` sets
`x-accel-buffering: no` on the `/events` proxy response. Without this, SSE
events arrive in batches rather than incrementally.

**Production:** `uv run koan` only. Python serves the built bundle.

```
python (:8000)  →  /static/app/*          →  frontend/dist/ (Vite build)
                →  /api/*, /events, /mcp/* →  existing routes (unchanged)
                →  /* (catch-all)          →  index.html (SPA fallback)
```

Build command: `cd frontend && npm run build`
Output: `koan/web/static/app/` (matches `base: '/static/app/'` in `vite.config.ts`)

**Starlette route order** in `create_app()` is significant — first match wins:

```
/mcp            → MCP endpoint
/api/*          → API handlers
/events         → SSE stream
/static/app     → StaticFiles (frontend/dist/)
/static         → other static assets
/{path:path}    → spa_fallback (index.html) — MUST be last
```

---

## State Model

Single Zustand store mirrors the backend projection. All live state enters
through the SSE bridge — nothing else writes to the store from outside the
component tree.

Key slices:

| Slice | Type | Source |
|---|---|---|
| `connected` | `boolean` | EventSource open/error |
| `lastVersion` | `number` | Snapshot or event version field |
| `runStarted` | `boolean` | Derived from first `phase_started` event |
| `phase` / `donePhases` | `string` / `string[]` | `phase_started` |
| `primaryAgent` | `AgentInfo \| null` | `agent_spawned`, `agent_step_advanced`, `agent_exited` |
| `scouts` | `Record<string, AgentInfo>` | `agent_spawned`, `agent_exited` |
| `activityLog` | `ActivityEntry[]` | `tool_called`, `tool_completed`, `thinking` |
| `streamBuffer` | `string` | `stream_delta`, `stream_cleared` |
| `activeInteraction` | `Interaction \| null` | `questions_asked`, `artifact_review_requested`, `workflow_decision_requested`, and resolution events. Stores `interactionType` (the event type string) alongside payload for component discrimination. |
| `artifacts` | `Record<string, ArtifactFile>` | `artifact_created`, `artifact_modified`, `artifact_removed` |
| `completion` | `CompletionInfo \| null` | `workflow_completed` |
| `notifications` | `NotificationEntry[]` | derived by fold from `agent_spawn_failed`, `agent_exited` with error |

`runStarted` gates top-level view (landing vs live). No router library — a
conditional render covers the binary choice.

`lastVersion` tracks the version of the last applied event or snapshot. The
SSE connection uses `?since=${lastVersion}` on connect/reconnect so the server
knows whether to send a snapshot or replay missed events.

### Store actions for the projection

```typescript
applySnapshot(data: SnapshotPayload): void
// Atomically replaces the entire store state from a snapshot.
// Called when the server sends event: snapshot.
// Uses useStore.setState(transform(data)) — one update, no merge logic.
// Any visual flash from the re-render is acceptable.

applyEvent(event: VersionedEvent): void
// Applies a single versioned event via the frontend fold.
// Called for every non-snapshot SSE event.
// Mirrors the backend fold cases exactly.
```

---

## SSE Bridge

`connectSSE(store)` in `sse/connect.ts` opens an
`EventSource('/events?since=${store.lastVersion}')` and handles two event
paths:

1. **`snapshot` event** → `store.applySnapshot(data)` — atomic state replace
2. **All other events** → `store.applyEvent(event)` — incremental fold

Returns the `EventSource`; `App.tsx` owns the reconnect lifecycle (exponential
backoff, capped at 5 s).

The bridge also handles `fatal_error` events (sent when `?since=N` references a
version the server no longer has, e.g. after server restart). On `fatal_error`,
the bridge closes the `EventSource` WITHOUT scheduling a reconnect and sets a
`fatalError` flag in the store. The UI renders a "reload required" banner.

### The frontend fold

The frontend fold mirrors the backend fold in `koan/projections.py`. Both must
produce the same projection shape from the same event sequence. When a new
event type is added to the backend, a corresponding fold case must be added to
the frontend `applyEvent`.

Fold cases match the backend exactly. See
[projections.md -- Fold cases](./projections.md#fold-cases) for the full table.

### Reconnect flow

```
Browser loads     → connect ?since=0   → snapshot   → applySnapshot → full state
Browser refreshes → connect ?since=0   → snapshot   → applySnapshot → full state
Connection drops  → reconnect ?since=N → events N+1..M → applyEvent each → up to date
```

**snake_case → camelCase mapping** happens in `applySnapshot` and `applyEvent`
for all agent payloads (`agent_id` → `agentId`, `started_at_ms` → `startedAt`,
etc.). The backend sends snake_case; the frontend transforms at the bridge
boundary.

**`phase_started` fold effect:** sets `runStarted = true` and derives
`donePhases`. This ensures a mid-run page reload (which receives a snapshot
with `run_started: true` and a current `phase`) restores the live view
correctly.

---

## Backend Contract

`ProjectionStore.push_event()` emits versioned events with fully-formed
payloads. Callers build complete payloads using helper functions; `push_event`
does not enrich payloads. See [projections.md](./projections.md) for the full
event type table and payload shapes.

All time values are UTC epoch milliseconds (`started_at_ms`). All token counts
are raw integers. Formatting is done client-side (`useElapsed`, `formatTokens`).

### Event builder helpers (Python)

| Helper | Produces event(s) | Notes |
|---|---|---|
| `build_agent_spawned(agent)` | `agent_spawned` | Extracts from `AgentState` |
| `build_agent_exited(agent_id, exit_code, error)` | `agent_exited` | |
| `build_agent_spawn_failed(role, diagnostic)` | `agent_spawn_failed` | |
| `build_artifact_diff(old, new)` | `artifact_created` / `artifact_modified` / `artifact_removed` | Diffs two artifact dicts |
| `build_tool_called(call_id, tool, args, summary)` | `tool_called` | |
| `build_tool_completed(call_id, tool, result)` | `tool_completed` | |

Settings endpoints (`/api/settings/body`, `/api/settings/profile-form`,
`/api/settings/installation-form`) return JSON. `SettingsOverlay.tsx` owns
form state and cascade dropdown logic.

---

## Component Mapping

| React component | Primary store subscription |
|---|---|
| `App.tsx` | `runStarted` |
| `LandingPage.tsx` | `runStarted` (negated) |
| `StatusSidebar.tsx` | `primaryAgent`, `phase` |
| `AgentMonitor.tsx` | `scouts` |
| `ArtifactsSidebar.tsx` | `artifacts` |
| `AskWizard.tsx` | `activeInteraction` |
| `WorkflowDecision.tsx` | `activeInteraction` |
| `ArtifactReview.tsx` | `activeInteraction` |
| `Completion.tsx` | `completion` |
| `SettingsOverlay.tsx` | `settingsOpen` + local state |
| `Notification.tsx` | `notifications` |

---

## Known Gaps (v1)

**`story` events** — emitted during execution phase with story lifecycle status.
Not implemented in v1: execution phase shows only primary agent status and
activity feed. Add a `stories` store slice and `StoryProgress` component when
designing the execution phase UI.


---

## Dependencies

```json
{
  "dependencies":    { "react": "^19", "react-dom": "^19", "zustand": "^5" },
  "devDependencies": { "typescript": "^5.7", "vite": "^6", "@vitejs/plugin-react": "^4" }
}
```

No router (two views, conditional render). No fetch library (typed `fetch`
wrappers in `api/client.ts`). No CSS framework (existing design tokens port
directly via CSS custom properties).
