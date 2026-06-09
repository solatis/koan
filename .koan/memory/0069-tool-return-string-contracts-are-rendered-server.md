---
title: Tool-return string contracts are rendered server-side, not in the frontend
type: decision
created: '2026-04-21T13:20:03Z'
modified: '2026-06-05T01:55:40Z'
related:
- 0110-review-phase-rewrite-or-loop-back-semantics.md
---

Tool-return string contracts -- the human-readable strings a tool returns that the orchestrator then pattern-matches on -- are owned and rendered by the backend, never by the frontend. The motivating case: a review-feedback formatter that had lived in the frontend (`formatReviewMessage()` in `frontend/src/App.tsx`) was ported into the backend tool layer, because when the orchestrator pattern-matches a tool's returned string (for example a sentinel like `"I've reviewed <path> and approve it as-is"`), a frontend-owned formatter silently couples orchestrator decision logic to UI refactors -- a React or store change could break the sentinel format and the Python test suite would never see it. Leon's generalizable rule: the frontend POSTs structured user input (for a review, a `{summary, comments: [{blockIndex, text, blockPreview}]}` payload) and the backend renders whatever string the orchestrator sees; any frontend-side copy of such a formatter exists only as short-lived refactor staging. Byte-exact parity on such a port is pinned by characterization tests that take the old frontend output as ground-truth fixtures.
