# UI Layout Redesign

Consolidate status information into the right panel, strip the header to
navigation-only, fix typography, and style scrollbars.

---

## Design Decisions

### Header = navigation, right panel = status

The header carries "where am I in the pipeline" (logo, phase pills, settings).
The right panel carries "what's happening right now" (agent identity, phase
progress, confidence, summary). No overlap between the two.

This eliminates three sources of redundancy: the ProgressBar (duplicates
PillStrip), the SubagentMeta bar (duplicates sidebar), and the Timer
(status, not navigation).

### The right panel is phase-aware for all phases

The current sidebar only renders meaningful content during intake. Every other
phase gets a generic "Phase in progress…" label. The redesign makes the panel
useful for every phase by showing phase-appropriate status widgets.

### Typography minimum: 12px

No text in the UI below 12px. The only 12px text is uppercase decorative
labels (CONFIDENCE, ITERATION). All readable content is 13px+. This is
the minimum for sustained reading on Retina displays.

### CSS-only scrollbar styling

Dark-themed thin scrollbar via `::webkit-scrollbar` and `scrollbar-width`.
No dependencies. Chromium-only support is sufficient — this is a localhost
developer tool.

---

## Changes

### 1. Remove ProgressBar

**Delete: `src/planner/web/js/components/ProgressBar.jsx`**

The 3px gradient bar at the top is a strict subset of the PillStrip's
information. The PillStrip already shows phase progression with ✓/● prefixes
and green/blue color states.

**File: `src/planner/web/js/components/App.jsx`**

Remove `<ProgressBar />` from the render tree and its import.

**File: `src/planner/web/css/layout.css`**

Remove `.progress-bar` and `.progress-fill` styles.

Update `.header` top position from `top: 3px` to `top: 0` (no progress bar
above it anymore).

Update `.main-panel` and `.live-layout` margin-top from
`calc(3px + var(--header-height))` to `var(--header-height)`.

### 2. Remove SubagentMeta bar

**Delete: `src/planner/web/js/components/SubagentMeta.jsx`**

Its content (role, model, step, tokens) moves into the top of the
StatusSidebar.

**File: `src/planner/web/js/components/App.jsx`**

Remove `<SubagentMeta />` from the live-layout render tree and its import.

**File: `src/planner/web/css/layout.css`**

Remove `.subagent-meta`, `.meta-role`, `.meta-item`, `.meta-tokens` styles.

### 3. Move Timer from header to sidebar

**File: `src/planner/web/js/components/Header.jsx`**

Remove `<Timer />` from the header and its import. The header-right div
keeps only the settings button.

If header-right has only the gear button and no other content, simplify
accordingly — but keep the flex layout for future additions.

### 4. Redesign StatusSidebar

**File: `src/planner/web/js/components/StatusSidebar.jsx`**

The sidebar becomes the single status home. It absorbs content from
SubagentMeta (agent identity) and Timer (elapsed time).

**New structure:**

```
┌─────────────────────────┐
│  INTAKE  ·  opus-4-6    │  agent role + model
│  Step 4/5: Reflect      │  step label
│  ↑39  ↓21k    15m 00s   │  tokens + timer
│─────────────────────────│
│                         │
│  [phase-specific status]│
│                         │
│─────────────────────────│
│  summary text           │
└─────────────────────────┘
```

**Agent identity section** (top, always present when subagent is active):

Read `subagent` from the store (same data SubagentMeta used). Display:

- Role (uppercase, blue) + model (muted) on one line
- Step label on the next line
- Token counts (↑sent ↓recv) + elapsed timer on the third line

Import the Timer logic (or inline a simple elapsed-time hook) — don't import
the Timer component since it's being deleted. Use `subagent.startedAt` to
compute elapsed time with a 1-second interval, same as the current Timer.

Use the `shortenModel` and `formatTokens` utilities from `lib/utils.js`.

**Phase-specific sections** (middle):

The sidebar already has `IntakeStatus` and `GenericStatus` branches. Keep
the IntakeStatus (confidence, iteration, sub-phase) as-is but with updated
typography. Expand GenericStatus into phase-specific variants:

```jsx
function PhaseStatus({ phase, stories }) {
  switch (phase) {
    case "intake":
      // handled separately via IntakeStatus
      return null;
    case "brief":
      return <BriefStatus />;
    case "decomposition":
      return <DecomposeStatus stories={stories} />;
    case "executing":
      return <ExecuteStatus stories={stories} />;
    default:
      return <GenericStatus phase={phase} />;
  }
}
```

- **BriefStatus**: "Drafting epic brief…" or "Awaiting review…" — simple
  label based on sub-phase (if we add brief sub-phase SSE events later,
  this can get richer. For now, a static label is fine.)

- **DecomposeStatus**: Show story count as stories arrive via the `stories`
  store slice. Example: "3 stories identified"

- **ExecuteStatus**: Show story progress from the `stories` store slice.
  Count stories by status. Example: "2/5 complete · 1 active"

- **GenericStatus** (fallback): simple label, same as current.

**Summary section** (bottom, below divider):

Keep the existing summary text pattern. For intake, use the sub-phase
summary map. For other phases, show a static contextual message.

**Visibility:** The sidebar should render whenever there is an active phase
in live mode — not only when `subagent` is non-null. During brief pauses
between subagent spawns, the phase-specific status (story progress, etc.)
is still useful. Gate on `phase` existence instead of `subagent` existence.
When `subagent` is null, just omit the agent identity section at the top.

### 5. Update App.jsx layout

**File: `src/planner/web/js/components/App.jsx`**

The live-layout block simplifies:

```jsx
<div class="live-layout">
  <div class="live-main">
    <main class="main-panel">
      <ActivityFeed />
    </main>
  </div>
  <StatusSidebar />
</div>
```

SubagentMeta and ProgressBar are gone. The live-main div now contains only
ActivityFeed (and AgentMonitor stays at the bottom, outside live-layout).

Remove imports: `ProgressBar`, `SubagentMeta`.

### 6. Widen sidebar + fix typography

**File: `src/planner/web/css/layout.css`**

Update sidebar width to be fluid:

```css
.status-sidebar {
  width: clamp(240px, 20vw, 300px);
  flex-shrink: 0;
  background: var(--bg-elevated);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: var(--gap-md) var(--gap-lg); /* was var(--gap-md) — more horizontal padding */
}
```

Update sidebar typography:

```css
.sidebar-heading {
  font-size: 12px; /* was 10px */
  margin-bottom: var(--gap-md);
}

.sidebar-label {
  font-size: 12px; /* was 10px */
}

.sidebar-value {
  font-size: 13px; /* was 12px (--font-size-xs) */
}

.sidebar-summary {
  font-size: 13px; /* was 11px */
}
```

Add new styles for the agent identity section:

```css
.sidebar-agent {
  margin-bottom: var(--gap-md);
  font-family: var(--font-mono);
}

.sidebar-agent-role {
  color: var(--blue);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 13px;
}

.sidebar-agent-model {
  color: var(--text-muted);
  font-size: 13px;
}

.sidebar-agent-step {
  color: var(--text-muted);
  font-size: 13px;
  margin-top: 2px;
}

.sidebar-agent-stats {
  display: flex;
  justify-content: space-between;
  color: var(--text-dim);
  font-size: 13px;
  margin-top: 2px;
}
```

### 7. Bump global typography

**File: `src/planner/web/css/variables.css`**

```css
--font-size-sm: 14px; /* was 13px */
```

This affects activity card headers, pill strip text, agent table text,
badge text, meta items — all the "secondary" text in the UI that was
slightly too small.

The other size variables stay the same:

- `--font-size-xs: 12px` (unchanged — labels, timestamps)
- `--font-size-md: 15px` (unchanged — body text)
- `--font-size-lg: 16px` (unchanged — headings, questions)

**File: `src/planner/web/css/layout.css`**

Update activity card body font size:

```css
.activity-card-body {
  font-size: 13px; /* was var(--font-size-xs) = 12px */
}
```

### 8. Style scrollbars

**File: `src/planner/web/css/variables.css`**

Add at the end of the file (after the `html, body` rule):

```css
/* Dark-themed scrollbar for all scrollable areas */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-ghost);
}
```

### 9. Clean up animation CSS

**File: `src/planner/web/css/animations.css`**

Remove the `.progress-fill` transition rule (the progress bar no longer
exists).

### 10. Update ARCHITECTURE.md component tree

**File: `src/planner/web/ARCHITECTURE.md`**

Update the component tree to reflect the new structure:

```
App
├── Header
│   ├── PillStrip        reads phase for active/done pill state
│   └── ⚙ settings btn
│
├── (isInteractive) main.main-panel
│   └── PhaseContent     dispatch hub
│
├── (live) div.live-layout
│   ├── div.live-main
│   │   └── main.main-panel
│   │       └── ActivityFeed        reads logs
│   └── StatusSidebar               agent identity + phase status + summary
│
├── AgentMonitor         reads agents (hides when none active)
└── Notifications        reads notifications
```

Remove ProgressBar and SubagentMeta from the tree description.

Update the StatusSidebar section to document:

- Agent identity section (role, model, step, tokens, timer)
- Phase-specific status for all phases (not just intake)
- Summary section

Update the "App layout modes" section — live mode no longer has SubagentMeta.

---

## Implementation Order

1. **Remove ProgressBar** — delete component, remove from App, clean up CSS
2. **Remove SubagentMeta** — delete component, remove from App, clean up CSS
3. **Move Timer out of header** — remove from Header.jsx (don't delete Timer.jsx yet — sidebar will reuse its logic)
4. **Redesign StatusSidebar** — absorb agent identity + timer, add phase-specific variants, update visibility gate
5. **Delete Timer.jsx** — if sidebar inlines the elapsed time logic; or keep it if sidebar imports it as a sub-component
6. **Widen sidebar + fix typography** — CSS updates
7. **Bump global typography** — `--font-size-sm` and activity card body
8. **Style scrollbars** — CSS-only addition
9. **Clean up animations CSS** — remove progress-fill rule
10. **Update ARCHITECTURE.md** — component tree and documentation

---

## Files Summary

| Action | File                                              | What                                                                                      |
| ------ | ------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Delete | `src/planner/web/js/components/ProgressBar.jsx`   | Redundant with PillStrip                                                                  |
| Delete | `src/planner/web/js/components/SubagentMeta.jsx`  | Absorbed into StatusSidebar                                                               |
| Modify | `src/planner/web/js/components/App.jsx`           | Remove ProgressBar + SubagentMeta imports and usage                                       |
| Modify | `src/planner/web/js/components/Header.jsx`        | Remove Timer import and usage                                                             |
| Modify | `src/planner/web/js/components/StatusSidebar.jsx` | Absorb agent identity + timer, phase-specific status                                      |
| Delete | `src/planner/web/js/components/Timer.jsx`         | Logic moves into StatusSidebar (or kept as imported sub-component)                        |
| Modify | `src/planner/web/css/variables.css`               | Bump `--font-size-sm`, add scrollbar styles                                               |
| Modify | `src/planner/web/css/layout.css`                  | Widen sidebar, fix typography, remove progress bar + subagent meta styles, fix header top |
| Modify | `src/planner/web/css/animations.css`              | Remove progress-fill transition                                                           |
| Modify | `src/planner/web/ARCHITECTURE.md`                 | Update component tree and docs                                                            |
