# Frontend

React + TypeScript SPA with a token-driven design system. Visual identity
is controlled by the user — agents implement it, they do not define it.

## Protected Files

These files require explicit user approval before any modification:

| File | Role | Why protected |
|------|------|---------------|
| `src/styles/variables.css` | All CSS design tokens | Tokens define the visual identity. Adding, renaming, or removing tokens changes the design language. |
| `docs/design-system.md` | Visual specification | The authoritative spec for every component's appearance. Changes here propagate to all components. |

If a task requires changing either file, describe the proposed change and
ask for approval. Do not apply it silently.

## Design System

The UI uses a token-driven design system documented in
[docs/design-system.md](../docs/design-system.md).

- **Tokens** are CSS custom properties defined in `src/styles/variables.css`
- **Components** reference tokens via `var(--token-name)` — never raw hex,
  px, or font-family values in component CSS
- If a value has no token, hardcode it in the component CSS with a comment
  explaining what it is and where it comes from, then tell the user so they
  can decide whether to promote it to a token

## Component Architecture

Components follow an atom → molecule → organism hierarchy in
`src/components/`:

| Tier | Directory | What it contains | Store access |
|------|-----------|------------------|--------------|
| Atoms | `atoms/` | Single visual elements (dots, badges, buttons) | Never |
| Molecules | `molecules/` | Compositions of atoms or elements (cards, rows, inputs) | Never |
| Organisms | `organisms/` | Page sections composing molecules (header bar, sidebar, forms) | Allowed |

**Read [src/components/AGENTS.md](src/components/AGENTS.md) when building,
modifying, or reviewing any UI component.** It contains the development
rules, CSS conventions, and verification checklist.

## Data Layer

These directories are the data layer. Do not modify them during visual work.

| Directory | Contains |
|-----------|----------|
| `src/store/` | Zustand store, state types, selectors |
| `src/sse/` | SSE connection, JSON Patch application |
| `src/api/` | Typed fetch wrappers |
| `src/hooks/` | useElapsed, useAutoScroll |

The store mirrors the backend projection via SSE. Components subscribe to
store slices and pass data to organisms/molecules as props.

## CSS Files

| File | Status | Rule |
|------|--------|------|
| `src/styles/variables.css` | Active — all tokens | **Protected** (see above) |
| `src/styles/app-shell.css` | Active — page frame layout | May modify for layout changes |
| `src/styles/markdown.css` | Active — rendered markdown | May modify carefully |
| `src/styles/components.css` | Legacy — only SettingsOverlay | Do not add new rules |
| `src/styles/layout.css` | Legacy — only SettingsOverlay | Do not add new rules |
| Component `.css` files | Active — colocated per component | All new styles go here |

## When to Ask the User

- Before modifying `variables.css` or `docs/design-system.md`
- When unsure whether a visual element should be an atom, molecule, or
  organism
- When a value needs to be used across multiple components (potential
  token promotion)
- When an existing component's visual spec doesn't match the design
  system document
