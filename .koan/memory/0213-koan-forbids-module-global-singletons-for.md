---
title: 'koan forbids module-global singletons for runtime/request state; per-run state
  is threaded explicitly (exceptions: connection pools and stats/metrics)'
type: procedure
created: '2026-06-12T23:04:54Z'
modified: '2026-06-12T23:04:54Z'
related:
- 0212-koans-in-run-memory-subsystem-resolves-models-and.md
- 0196-koan-freezes-a-runs-resolved.md
---

koan threads per-run and request-scoped state explicitly -- through `app_state`, through the per-run frozen snapshot on `RunState`, or as ordinary function arguments -- rather than reaching for process-wide module-global singletons. Leon set this as a non-negotiable project rule on 2026-06-12, after a module-global credential/model seam in the memory subsystem (`koan/memory/bindings.py`, `koan/credentials.py`) let two code paths silently diverge: in-run memory resolved its model from the per-run frozen snapshot but its API key from a boot-time module global, so the model and its credential could come from different copies of state.

The rule: when a component needs runtime, configuration, credential, resolved-model, or active-run state, do NOT introduce a module-level singleton -- no `_ACTIVE`-style global set once at boot with `set_`/`get_` accessors, no process-wide cache standing in for per-run state. Thread the state explicitly to the component's entry point and pass it down. 'This module has no app_state' is not a license for a global: give it the state at its boundary (for example, the standalone `koan memory` CLI builds its own resolved models at process entry and threads them through the same parametrized interface the in-run path uses, instead of reading a global).

The only acceptable exceptions are connection pools and stats/metrics accumulators, and even those should be avoided wherever a threaded alternative is workable. Rationale: explicit-over-implicit -- ambient globals hide a component's true dependencies at its signature, let two paths read different copies of the same logical state, and make per-run isolation impossible to guarantee.
