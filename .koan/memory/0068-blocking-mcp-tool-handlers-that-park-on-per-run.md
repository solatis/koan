---
title: Blocking in-process handlers that park on per-run asyncio futures guard against
  reentry
type: procedure
created: '2026-04-21T13:19:51Z'
modified: '2026-06-04T14:26:53Z'
related:
- 0158-koanyield-removed-the-agent-loops-terminal-text.md
---

Any in-process handler that parks on a per-run `asyncio.Future` stored on `AppState.interactions` -- the blocking interaction tools and the agent loop's hand-back -- guards against reentry before parking: it reads the existing future for that slot, and if that future is set and not yet done, it refuses (raises an `already_pending` error, or logs and skips) instead of overwriting. The reason: reassigning the slot while a prior caller is still awaiting drops that caller's resolution handle, so its `await` parks forever. The agent loop applies this guard to its `yield_future` -- it logs and skips the hand-back park if a prior yield is somehow still pending -- and the blocking interaction handlers (`koan_ask_question`, `koan_memory_propose`) raise on reentry rather than silently replacing the pending future. Assigning the future unconditionally is the wrong approach: under any reentrant control flow it strands the earlier waiter.
