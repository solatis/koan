---
title: 'Koan frontend: subscribe to narrow stable leaf slices and memoize lists at
  a per-entry boundary -- Immer structural sharing re-references every node on a touched
  path each patch'
type: procedure
created: '2026-06-18T00:38:52Z'
modified: '2026-06-18T00:38:52Z'
related:
- 0205-re-sync-editable-local-react-state-from-a.md
- 0222-koan-frontend-rendering-reshaped-to-a-reagentre.md
---

In the koan frontend the Zustand store mirrors the backend SSE projection and `frontend/src/sse/connect.ts` applies each patch with Immer `produce` (structural sharing). When a React component reads projection state on the streaming hot path (the conversation view and its children), subscribe to the narrowest stable leaf slice through a shared selector in `frontend/src/store/selectors.ts` -- never subscribe to `s.run`, `s.run.agents`, or a whole `conversation` by reference. Immer's copy-on-write gives every node along a touched path (root -> run -> agents -> [id] -> conversation -> the changed field) a new reference, so a coarse `useStore(s => s.run)` subscription re-renders on every patch, including each streamed token. Two companion rules: a selector must return a referentially stable value when its slice is absent (a module-level frozen EMPTY constant, never a fresh `[]`/`{}`, or `useSyncExternalStore` forces spurious re-renders); and a long list is memoized at a per-entry component boundary (`React.memo` comparing the reference-stable entry object, keyed by its stable `entry_id`), not by wrapping the leaf molecules in `React.memo` -- a parent that recreates each row's `<Md>` children element every render defeats the molecules' shallow prop compare, so leaf-molecule memo never bails. Violating these reintroduces O(history)-per-token re-rendering and react-markdown re-parsing of the whole conversation.
