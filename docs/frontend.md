# Frontend

React 19 + Zustand 5 + Vite 6 SPA. Python serves the built bundle as static
files — no Node.js in production.

> Parent doc: [architecture.md](./architecture.md)

---

## Directory Layout

```
frontend/
├── AGENTS.md               # frontend-specific agent rules (read first)
├── package.json
├── tsconfig.json
├── vite.config.ts          # proxies /api/*, /events, /mcp/* to Python in dev
├── index.html              # Vite entry point
├── src/
│   ├── main.tsx            # mounts <App /> into #root; imports global CSS
│   ├── App.tsx             # top-level layout; owns SSE connection lifecycle
│   ├── utils.ts            # formatTokens, formatSize, normalizeOptions
│   ├── store/
│   │   ├── index.ts        # single Zustand store (the app-db equivalent)
│   │   └── selectors.ts    # derived state computed from store slices
│   ├── sse/
│   │   └── connect.ts      # EventSource wrapper: always-snapshot catch-up + JSON Patch
│   ├── api/
│   │   └── client.ts       # typed fetch wrappers for POST/PUT endpoints
│   ├── components/
│   │   ├── AGENTS.md       # component development rules (read when building components)
│   │   ├── atoms/          # StatusDot, Badge, Button, SectionLabel, LogoMark, ProgressSegment
│   │   ├── molecules/      # ProseCard, ThinkingBlock, ToolCallRow, FeedbackInput, etc.
│   │   ├── organisms/      # HeaderBar, ScoutBar, ArtifactsSidebar, ElicitationPanel, NewRunForm
│   │   ├── Md.tsx          # shared markdown renderer (ReactMarkdown + remark-gfm)
│   │   ├── Notification.tsx # toast notification system
│   │   └── SettingsOverlay.tsx # settings modal (not yet redesigned)
│   ├── hooks/
│   │   ├── useElapsed.ts   # elapsed time hook for agent start times
│   │   └── useAutoScroll.ts # sticky-scroll for content stream
│   └── styles/
│       ├── variables.css   # design tokens (PROTECTED — see frontend/AGENTS.md)
│       ├── app-shell.css   # page frame layout (.app-root, .workflow-grid)
│       ├── markdown.css    # rendered markdown content styling
│       ├── layout.css      # legacy — SettingsOverlay only
│       └── components.css  # legacy — SettingsOverlay only
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

Store slices:

| Slice | Type | Source |
|---|---|---|
| `connected` | `boolean` | EventSource open/error |
| `lastVersion` | `number` | Snapshot/patch version |
| `settings` | `Settings` | installations, profiles, defaultProfile, defaultScoutConcurrency |
| `run` | `Run \| null` | config, phase, agents, focus, artifacts, completion |
| `notifications` | `Notification[]` | message, level, timestampMs |
| `settingsOpen` | `boolean` | Local UI state (not from server) |

`run` being `null` vs non-null gates the top-level view (landing vs live). No
router library — a conditional render covers the binary choice.

`lastVersion` tracks the version of the last applied snapshot or patch. The SSE
connection sends `?since=${lastVersion}` on connect/reconnect so the server
knows where the client left off.

### Store actions

```typescript
setConnected(v: boolean): void
// Sets the connected flag. Called by connectSSE on EventSource open/error.

setSettingsOpen(v: boolean): void
// Toggles the settings panel. Called by UI controls only.
```

State updates from the server (snapshots and patches) are applied directly via
`store.setState()` inside the SSE bridge — not through named actions.

---

## SSE Bridge

`connectSSE(store)` in `sse/connect.ts` opens an
`EventSource('/events?since=${lastVersion}')` and handles two event paths:

1. **`snapshot` event** — atomically replaces the entire store state.
   Parses `{ version, state }` from the event data, sets `storeState = state`,
   then calls `store.setState({ lastVersion: version, ...state })`.

2. **`patch` event** — applies an RFC 6902 JSON Patch via `fast-json-patch`.
   Parses `{ version, patch }`, calls `applyPatch(storeState, patch, false, false)`
   with `mutate: false` to get a new document, then spreads the result into the
   store with the updated `lastVersion`.

   On patch failure, the bridge logs the error, closes the `EventSource`, and
   resets `lastVersion` to `0` to force a fresh snapshot on reconnect. The
   `onerror` handler in `App.tsx` then schedules the reconnect.

Returns the `EventSource`; `App.tsx` owns the reconnect lifecycle (exponential
backoff, capped at 5 s).

### Reconnect flow

```
Browser loads     → connect ?since=0   → snapshot → state replace → full state
Browser refreshes → connect ?since=0   → snapshot → state replace → full state
Connection drops  → reconnect ?since=N → snapshot (if N≠server version) → full state
Patch failure     → reconnect ?since=0 → snapshot → state replace → full state
```

The server always sends a snapshot when the client's `since` version does not
match the current server version, so clients never need to track or replay
individual events — a reconnect always converges to current state.

---

## Backend Contract

`ProjectionStore.push_event()` emits versioned events with fully-formed
payloads. Callers build complete payloads using helper functions; `push_event`
does not enrich payloads. See [projections.md](./projections.md) for the full
event type table and payload shapes.

All time values are UTC epoch milliseconds (`startedAtMs`). All token counts
are raw integers. Formatting is done client-side (`useElapsed`, `formatTokens`).

The backend sends camelCase field names natively via `KoanBaseModel.to_wire()`.
No field name transformation is needed in the frontend.

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

## Component Architecture

Components follow an atom → molecule → organism hierarchy. See
[frontend/src/components/AGENTS.md](../frontend/src/components/AGENTS.md)
for development rules.

**Organisms and their store subscriptions:**

| Organism | Store subscription | Wiring |
|---|---|---|
| `HeaderBar` | `run.phase`, `run.agents` (primary) | `useHeaderData()` hook in App.tsx |
| `NewRunForm` | `settings.profiles`, `settings.installations` | Reads store directly |
| `ElicitationPanel` | `run.focus` (questions) | `ElicitationView` in App.tsx |
| `ArtifactsSidebar` | `run.artifacts` | `ConnectedSidebar` in App.tsx |
| `ScoutBar` | `run.agents` (non-primary) | `ConnectedScoutBar` in App.tsx |
| `SettingsOverlay` | `settingsOpen` + local state | Direct store access |

**Content stream rendering** maps each conversation event type to a molecule.
The full mapping is documented in
[docs/design-system.md](./design-system.md#content-stream-rendering) and in
[frontend/src/components/AGENTS.md](../frontend/src/components/AGENTS.md).

Scouts are agents where `isPrimary === false`. App.tsx filters `run.agents`
by this flag — there is no separate `scouts` slice.

---

## Known Gaps (v1)

**`story` events** — emitted during execution phase with story lifecycle status.
Not implemented in v1: execution phase shows only primary agent status and
activity feed. Add a `stories` field inside `Run` and a `StoryProgress`
component when designing the execution phase UI.


---

## Dependencies

```json
{
  "dependencies":    { "react": "^19", "react-dom": "^19", "zustand": "^5", "fast-json-patch": "^3" },
  "devDependencies": { "typescript": "^5.7", "vite": "^6", "@vitejs/plugin-react": "^4" }
}
```

No router (two views, conditional render). No fetch library (typed `fetch`
wrappers in `api/client.ts`). No CSS framework (existing design tokens port
directly via CSS custom properties).
