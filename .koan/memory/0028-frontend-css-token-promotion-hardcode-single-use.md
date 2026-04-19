---
title: Frontend CSS token promotion -- hardcode single-use values, flag multi-component
  values, never modify variables.css unilaterally
type: procedure
created: '2026-04-16T09:26:15Z'
modified: '2026-04-16T09:26:15Z'
---

The koan frontend design system uses CSS custom properties defined in `frontend/src/styles/variables.css` as the sole source of design tokens. On 2026-04-16, the component development rules in `frontend/src/components/AGENTS.md` established the token promotion rule for agents implementing frontend components. The maintainer established three tiers of handling for CSS values: (1) values used by exactly one component -- hardcode in that component's colocated `.css` file with a descriptive comment explaining what the value represents; (2) values used by multiple components, or clearly about to be -- flag for token promotion in the response to the user, do not add the token yourself; (3) `variables.css` is a protected file requiring explicit user approval before any modification -- agents must never add, rename, or remove tokens unilaterally. The class naming convention was also established: prefix CSS class names with a short component abbreviation to avoid collisions (e.g., `.tcr-` for ToolCallRow, `.hb-` for HeaderBar, `.ep-` for ElicitationPanel). The maintainer further established that `npx tsc --noEmit` must be run after any TypeScript/TSX changes to verify zero compilation errors before considering frontend work done.
