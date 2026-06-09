---
title: Top-level SPA page routes must mount inside .single-column; missing wrapper
  silently breaks vertical scroll
type: lesson
created: '2026-04-22T04:10:55Z'
modified: '2026-04-22T04:10:55Z'
---

This entry records a UI scroll bug in the koan frontend SPA's memory area. On 2026-04-22, Leon reported that the Memory overview page at `/memory` did not scroll vertically when its content (summary card, stat strip, activity list) exceeded the viewport height, even though the sibling `new-run` and `sessions` pages and the embedded MemorySidebar (`.ms`) scrolled correctly. Direct reading traced the root cause: `frontend/src/App.tsx` wrapped the `new-run` and `sessions` routes in `<div className="single-column">` (declared in `frontend/src/styles/app-shell.css` with `flex:1; min-height:0; overflow-y:auto`) but mounted `<MemoryRoutes />` directly under `.app-root`, which itself has `height:100vh; overflow:hidden`. Without a scrolling ancestor the memory page could not scroll -- the sidebar worked only because `.ms` set its own `overflow:auto`. Correction applied the same day in `frontend/src/App.tsx`: wrap `<MemoryRoutes />` in `<div className="single-column">` alongside the other nav branches. The generalizable rule recorded here is that any top-level page reachable from the `NAV_ITEMS` palette must sit inside `.single-column` or an equivalent `overflow-y:auto` container; `.app-root` is not a scroll parent.
