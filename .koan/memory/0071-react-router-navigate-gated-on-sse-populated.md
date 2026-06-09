---
title: React-Router <Navigate> gated on SSE-populated store slices causes URL-bounce
  flashes; use inline empty state
type: lesson
created: '2026-04-22T04:10:59Z'
modified: '2026-04-22T04:10:59Z'
---

This entry records a UI rendering bug in the memory reflect route (`/memory/reflect`) of the koan frontend SPA. On 2026-04-22, Leon reported a visible flash after clicking "Ask" on the Memory overview: the URL changed to `/memory/reflect` and then immediately bounced back to `/memory`, with real backend requests continuing in the background. Direct reading of `frontend/src/components/organisms/MemoryRoutes.tsx` identified the root cause: `ConnectedMemoryReflect` rendered `<Navigate to="/memory" replace />` whenever the `reflect` slice of the Zustand store was null. `handleAsk` awaited `api.startReflect(q)` and then called `navigate('/memory/reflect')`, but the `reflect_started` SSE event that populates the store slice is delivered on a separate channel and applies asynchronously to the POST response -- so the React-Router route mounted with `reflect === null`, fired `<Navigate>`, and bounced the URL before SSE caught up. Direct-URL entry to `/memory/reflect` with no active session hit the same bounce. Correction applied the same day: remove the `<Navigate>` path entirely and render an inline `ReflectPaneEmpty` placeholder inside the `.mrp` grid shell when `reflect` is null. The generalizable rule is that route-level early-return redirects (`<Navigate>`) gated on asynchronously-populated state create this race; render an inline empty state instead, letting the next SSE-driven render swap the placeholder for the real content without a URL transition.
