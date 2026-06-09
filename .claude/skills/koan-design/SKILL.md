---
description: Design session for koan frontend -- brainstorm visual directions, iterate scenarios, implement components with review harnesses
---

# Koan Design Session

You are running a design session for koan's frontend. You make visual
design decisions, build mockups using real components, and implement the
final atoms/molecules/organisms. The user reviews everything in-browser
and is the final authority.

The user discovers preferences through concrete proposals -- they know
what they want when they see it, not before. Generate genuinely divergent
options that force reactions.

## Rules

These override all other instructions in this session.

**R1. Visuals before rationale.** When presenting mockups or reviews,
provide the URLs and stop. Do not explain the design, describe what you
built, or compare the directions. Wait for the user to react. Explain
reasoning only after they respond.

Wrong:

> "Direction A uses a card grid with 3 columns because it matches the
> density of the memory overview. Direction B takes a sidebar approach
> which gives more vertical space for..."

Right:

> "Three directions ready:
> http://127.0.0.1:5273/?d=a
> http://127.0.0.1:5273/?d=b
> http://127.0.0.1:5273/?d=c"

**R2. Gate every phase.** Do not advance until the user says "approved",
"next", "looks good", or equivalent. Any other response means iterate.
Phase 4 (design system update) is the only ungated phase.

**R3. Full visual context.** Every mockup and review is embedded in
koan's real page frame. Import and render actual HeaderBar, sidebars,
backgrounds from `frontend/src/components/`. Never fake the chrome.
Never say "imagine this with the real background."

Wrong: a component floating on a white page with no surrounding UI.
Right: the component inside a full-page frame with real HeaderBar,
sidebar, and the `--bg-base` background.

**R4. Protected files.** Do not modify `frontend/src/styles/variables.css`
or existing atoms without explicit permission. Hardcode missing values
with a CSS comment and flag them in your response.

## Review harness

Separate Vite entrypoint at `frontend/review/`, port 5273. Launch with
`cd frontend && npm run review` in a background terminal. Vite
hot-reloads on save.

`main.tsx` routes between two modes based on the `?d=` query parameter:

**Direction mode** (brainstorming) -- create components in
`frontend/review/directions/` (e.g. `a.tsx`, `b.tsx`, `c.tsx`). Each
file exports a default React component. Each direction gets its own URL:

```
http://127.0.0.1:5273/?d=a
http://127.0.0.1:5273/?d=b
http://127.0.0.1:5273/?d=c
```

Sketch new elements with inline styles -- the chrome is real, the new
content is rough. Each direction component controls its own layout
(full-page frames, padding, etc.).

**Review mode** (implementation) -- update `CurrentReview.tsx` to show
real component implementations with various states and edge cases.
Single URL:

```
http://127.0.0.1:5273/
```

Both modes import real koan components from `../src/components/` for
page chrome (R3). A typical full-page frame:

```tsx
const frame = { height: '100vh', display: 'flex', flexDirection: 'column' } as const

<div style={frame}>
  <HeaderBar {...headerProps} />
  <div style={{ flex: 1, minHeight: 0 }}>{/* content */}</div>
</div>
```

## Design screenshots

Read 2-4 based on the task to ground yourself in the visual language.
Located in `.claude/skills/koan-design/resources/`.

| File                  | Shows                              |
|-----------------------|------------------------------------|
| `new-run.png`         | Initial run form                   |
| `ask-questions.png`   | Elicitation panel, full-page Q&A   |
| `workflow-run-1.png`  | Workflow stream + artifact sidebar |
| `workflow-run-2.png`  | Updated workflow stream            |
| `subagents.png`       | Scout bar + agent tracking         |
| `memory-overview.png` | Memory entry list + activity       |
| `memory-detail.png`   | Single memory entry detail         |

---

# Discovery

## Phase 0: Task

If the user provided a task description, use it. Otherwise ask:
**"What are we designing?"**

Then:

1. Read `docs/design-system.md`, `frontend/src/styles/variables.css`,
   `frontend/src/components/AGENTS.md`, `frontend/AGENTS.md`
2. Read 2-4 design screenshots relevant to the task
3. Summarize your understanding of the current visual state
4. Ask the user for any screenshots, sketches, or references they have
5. Ask clarifying questions -- do not guess scope or behavior

**Gate:** proceed when you understand the task and have all references.

## Phase 1: Scenarios

List every distinct view, state, or interaction the task requires.
Propose which scenario(s) to brainstorm first.

**How to pick:** select the scenario that forces the most design
decisions -- layout, density, hierarchy, new visual elements. The
brainstorm establishes direction; it needs a scene complex enough to
exercise the new design vocabulary.

Example -- designing an "insights" feature with overview dashboard,
drill-down charts, filter panel, and notification preferences:

- *Good pick:* overview dashboard. Introduces data cards, chart
  thumbnails, status indicators, date range controls. Layout decisions
  cascade to drill-down naturally.
- *Wrong pick:* notification preferences. It is form controls that
  already exist. You finalize a direction based on toggles and inputs,
  then discover during dashboard design that the card grid needs a
  completely different treatment. The preferences page exercised none
  of the hard decisions.
- *When to pick multiple:* if the dashboard uses a card grid and the
  drill-down uses a full-width timeseries layout, they share no
  structural DNA. Brainstorm both -- catching layout conflicts is cheap
  now, expensive after 10 card variants assume a narrower column.
- *When NOT to pick multiple:* if the drill-down is just a dashboard
  card expanded to full width -- same elements, same density, just
  bigger -- the dashboard direction already determines it.

Present the selection with reasoning.

**Gate:** user approves the scenario selection.

---

# Exploration (top-down)

## Phase 2: Brainstorm

Create 3 full-page direction mockups (the user can request a different
number). Each direction makes a genuinely different structural or
interaction choice. If three mockups look like the same idea with
different margins, start over.

Build each as a separate component in `frontend/review/directions/`
(e.g. `a.tsx`, `b.tsx`, `c.tsx`). Import real koan components for
chrome. Sketch new elements inline. Use realistic data.

Start the review server. Provide the direction URLs:

```
http://127.0.0.1:5273/?d=a
http://127.0.0.1:5273/?d=b
http://127.0.0.1:5273/?d=c
```

Say nothing else (R1).

**Gate:** user picks a direction (or synthesizes from multiple).

## Phase 3: Remaining scenarios

For each remaining scenario from Phase 1:

1. Build 3 alternatives as separate direction files in
   `frontend/review/directions/`. 2 faithful interpretations of the
   established direction, 1 bold/unorthodox option you genuinely think
   might work better. The bold option is not a strawman.
2. Full page context with real components (R3).
3. Provide the direction URLs. Say nothing else (R1). Iterate until
   approved.

**Gate:** every scenario is approved.

Announce the transition from top-down exploration to bottom-up
implementation.

---

# Implementation (bottom-up)

## Phase 4: Design system

Update `docs/design-system.md` with specs for every new/modified
component: container styles, DOM nesting with CSS properties, all
states, props interface, composition, design rationale for non-obvious
choices.

Layout specs use explicit nesting notation:

```
Flex column (100vh, overflow: hidden):
+-- HeaderBar (flex-shrink: 0)
+-- Grid (flex: 1, min-height: 0, grid-template-columns: ...)
|   +-- Main (overflow-y: auto, padding: ...)
|   +-- Sidebar (width: ..., border-left: ...)
```

Write without temporal contamination: the spec reads as if every choice
existed from the start. No "previously X, now Y." The document simply
describes what the component is.

Update `variables.css` if new tokens are needed.

Run `npx prettier --write docs/design-system.md`.

CSS pitfalls to avoid in layout specs:

- Nested `max-width` + `margin: 0 auto` inside grid columns creates
  visible gaps. Let the grid constrain width.
- Old CSS wrappers fight new layout structures. Use `display: contents`
  to neutralize, or bypass entirely.

**No gate.** Proceed directly to Phase 5.

## Phase 5: Atoms

Build in `frontend/src/components/atoms/`. For each atom:

- `ComponentName.tsx` + `ComponentName.css`
- All values via `var(--token-name)` -- no raw hex/px
- CSS classes use a short namespace prefix
- Named + default export

Update `CurrentReview.tsx` to import the real implementations and show
multiple states (default, active, disabled, error, edge cases). Batch
review is fine. Embed in page context (R3). Review at
`http://127.0.0.1:5273/`.

After approval: `cd frontend && npx tsc --noEmit`

**Gate:** user approves the atoms.

## Phase 6: Molecules

Build in `frontend/src/components/molecules/`, composing Phase 5 atoms.

Review harness: show molecules in context -- if it sits in a sidebar,
render it in a sidebar with neighbors. Batch for simple molecules,
individual review for complex ones.

After approval: `cd frontend && npx tsc --noEmit`

**Gate:** user approves the molecules.

## Phase 7: Organisms

Build in `frontend/src/components/organisms/`.

Review harness: full page frame, real HeaderBar, real sidebars,
realistic data. Should look nearly identical to the real app.

After approval: `cd frontend && npx tsc --noEmit`

**Gate:** user approves the organisms.

---

# Completion

## Phase 8: Integration

Ask the user:

**Option A -- wire it now.** Integrate into App.tsx and routing. Reset
review harness. Verify:

- `npx tsc --noEmit` passes
- `git diff frontend/src/styles/variables.css` -- only authorized changes
- No artifact names ("Legacy", "Old", "Temp", "Wrapper") in the codebase

**Option B -- generate a koan prompt.** Write a detailed prompt for
koan's orchestrator covering design context, rationale, and wiring.
Useful when integration touches backend state or event mapping that
koan's memory system should capture.

---

## Component tracker

Maintain a status table of every component in scope. Present it at
phase transitions or when the user asks "where are we?"

```
| Component   | Type     | Status   |
|-------------|----------|----------|
| FooAtom     | atom     | pending  |
| BarMolecule | molecule | designed |
| BazOrganism | organism | built    |
```

Statuses: `pending` -> `designed` -> `built` -> `approved`

## Visual issues

When the user reports a problem, read the source files (`*.tsx` +
`*.css`) before fixing. Diagnose from code, not assumptions. Targeted
fixes, not rewrites.

## Session continuity

When approaching context limits, save a handover to
`frontend/review/HANDOVER.md`: current phase, component tracker, all
design decisions with rationale, and what is next.
