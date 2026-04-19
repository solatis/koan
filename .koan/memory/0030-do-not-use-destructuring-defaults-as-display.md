---
title: Do not use destructuring defaults as display-value fallbacks for potentially
  absent React props
type: procedure
created: '2026-04-16T11:29:39Z'
modified: '2026-04-16T11:29:39Z'
related:
- 0029-headerbar-rendered-phantom-opus-model-label.md
---

Koan's frontend component conventions, established on 2026-04-16 during the fix of a phantom model label in `frontend/src/components/organisms/HeaderBar.tsx`, include the following rule for handling potentially absent props. When a React component prop is typed `T | undefined` and `undefined` means 'data is genuinely absent' (not just unspecified), using a destructuring default that provides a display-value string -- e.g., `orchestratorModel = 'opus'` -- masks the absence and causes the UI element to render when it should not. The correct pattern, confirmed by the user on 2026-04-16, is: (a) omit the destructuring default so the parameter retains `undefined`; (b) use conditional rendering (`{prop && <Section />}`) to suppress the UI element entirely. This rule applies to any component where an absent prop signals 'nothing to show' rather than 'use a sensible default'.
