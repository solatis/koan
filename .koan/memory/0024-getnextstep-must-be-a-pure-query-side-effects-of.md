---
title: '`get_next_step()` must be a pure query; side effects of loop-backs belong
  in `on_loop_back()`'
type: procedure
created: '2026-04-16T09:03:11Z'
modified: '2026-04-16T09:03:11Z'
related:
- 0013-single-cognitive-goal-per-step-prevents-simulated.md
---

The koan phase module protocol, defined in `koan/phases/__init__.py`, requires phase modules to implement `get_next_step(step, ctx)` and optionally `on_loop_back(from_step, to_step, ctx)`. On 2026-04-16, the architecture documentation in `docs/architecture.md` established the invariant that `get_next_step()` must be a pure query -- it returns the next step number and nothing else. The maintainer documented the anti-pattern: placing state mutations (counter increments, setting `ctx.confidence = None`), event emissions, or I/O inside `get_next_step()` violates the contract because the function may be called multiple times in a single step transition. The documented correct pattern was: `get_next_step()` returns a step number only; any state changes that must accompany a backward step transition belong in `on_loop_back(from_step, to_step, ctx)`. The maintainer provided a concrete example: `get_next_step(4)` returning `2` for a loop-back is correct; incrementing `self.iteration` inside that call is wrong -- `self.iteration += 1` belongs in `on_loop_back(4, 2, ctx)`.
