# Component Development Rules

Read this file when building, modifying, or reviewing UI components.

## Hierarchy

**Atoms** (`atoms/`): The foundation. Pure visual primitives.
- No imports from other atoms, molecules, or organisms
- No store access, no API calls, no side effects
- Props control all behavior — fully presentational
- Examples: StatusDot, Badge, Button, SectionLabel, LogoMark

**Molecules** (`molecules/`): Composed from atoms or plain elements.
- May import atoms — never other molecules or organisms
- No store access — controlled entirely via props
- Each molecule handles one visual concept
- Examples: ToolCallRow, ProseCard, ThinkingBlock, RadioOption

**Organisms** (`organisms/`): Page-level sections.
- Compose molecules and atoms into layout regions
- May access the store directly (NewRunForm does) or receive props
  from a `Connected*` wrapper in App.tsx
- Examples: HeaderBar, ScoutBar, ElicitationPanel, NewRunForm

**Deciding the tier:**
1. Single styled element with no children? → **Atom**
2. Composes atoms into a self-contained visual unit? → **Molecule**
3. Composes molecules into a page section with layout? → **Organism**
4. Uncertain? Start as a molecule. Promote later if needed.

## CSS Conventions

Every component gets a colocated `.css` file (e.g., `ProseCard.css`).

**Token discipline:**
- All colors, fonts, sizes, spacing, and radii reference tokens via
  `var(--token-name)`
- Never use raw hex values, pixel sizes, or font-family strings in
  component CSS
- One-off decorative values (SVG stroke colors, icon fills) may be
  hardcoded with a comment explaining origin:
  `/* lavender dot — from thinking palette */`
- After hardcoding, flag it in your response so the user can decide
  whether it warrants a token

**The promotion rule:**
- Value used by ONE component → hardcode in that component's CSS with
  a descriptive comment
- Value used by MULTIPLE components, or clearly about to be → flag it
  for token promotion. Do not add the token yourself.
- `variables.css` is protected — modification requires user approval

**Class naming:** Prefix CSS class names with a short component
abbreviation to avoid collisions: `.tcr-` (ToolCallRow), `.hb-`
(HeaderBar), `.ep-` (ElicitationPanel).

## Building a New Component

1. **Create** `ComponentName.tsx` + `ComponentName.css` in the correct
   tier directory
2. **Write** the component with TypeScript props, JSDoc comment
   describing purpose and usage
3. **Style** using tokens from `variables.css` — check available tokens
   before hardcoding anything
4. **Export** as both named and default export
5. **Integrate** into the parent component

### Review Harness Protocol

For visual verification of new components:

1. Create `ReviewComponentName.tsx` in the same directory
2. In App.tsx, add a temporary import and route:
   ```tsx
   import { ReviewX } from './components/molecules/ReviewX'
   const reviewParam = new URLSearchParams(window.location.search).get('review')
   // then in the render: if (reviewParam === 'x') return <ReviewX />
   ```
3. View at `http://localhost:5173/?review=x`
4. After approval, delete the review harness and remove the App.tsx changes
5. Commit the component only — never the harness

## Content Stream Event Mapping

Every conversation event type renders through a molecule. No inline CSS
class renderings for event types.

| Event type | Molecule |
|---|---|
| `thinking` | ThinkingBlock + Md |
| `text` | ProseCard + Md |
| `tool_read/write/edit/bash/grep/ls` | ToolCallRow |
| `tool_generic` | ToolCallRow |
| `step` | StepHeader |
| `debug_step_guidance` | StepGuidancePill + Md |
| `user_message` | UserBubble + Md |
| `phase_boundary` | PhaseMarker |
| `yield` | YieldPanel |
| pending thinking | ThinkingBlock (always expanded) |
| pending text | ProseCard + Md + streaming cursor |
| steering messages | SteeringBar |

When encountering a new event type with no molecule: render as ProseCard
with raw content and flag it for a dedicated molecule.

## Verification Checklist

Before considering component work done:

- [ ] TypeScript compiles with zero errors (`npx tsc --noEmit`)
- [ ] All CSS values reference tokens — no raw hex or px (except
      flagged one-off decoratives)
- [ ] No references to old/deleted token names remain (grep the
      codebase)
- [ ] Component is in the correct tier directory
- [ ] CSS class names use the component's namespace prefix
- [ ] `docs/design-system.md` has a spec for this component (or
      you've flagged that it needs one)
- [ ] Review harness is deleted before committing

## Do Not Modify

During component work, do not touch:

- `src/store/`, `src/sse/`, `src/api/`, `src/hooks/` — data layer
- `src/styles/variables.css` — requires user approval
- `src/styles/components.css`, `src/styles/layout.css` — legacy files,
  do not add new rules
- Existing atoms — they are the foundation; changes require approval
