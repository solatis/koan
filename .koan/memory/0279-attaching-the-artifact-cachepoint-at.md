---
title: Attaching the artifact CachePoint at message_history[-1] leaks the long TTL
  onto the churny conversation tail on turns 2+
type: lesson
created: '2026-07-03T08:51:03Z'
modified: '2026-07-03T08:51:03Z'
related:
- 0161-cache-prefix-stability-is-load-bearing-a-byte.md
- 0261-koan-clears-the-orchestrators-message-history-at.md
---

While implementing koan's `cache_artifacts` breakpoint, an early design attached the long-TTL `CachePoint` to `agent.message_history[-1]`. This was correct only on the phase-entry turn, when `[-1]` is the freshly-preseeded artifact/listing message. Root cause: `run_agent_loop` (`koan/agents/loop.py`) replaces `message_history` with `agent_run.all_messages()` each turn, so on turns 2+ `[-1]` is the churny tail -- a `ModelResponse`, a tool-return `ModelRequest`, or a steering/user `ModelRequest` -- and attaching the long (`1h`) TTL there inverts the cache policy's goal, wasting cache-write cost on the fastest-churning region every turn. Prevention: the injection layer identifies the target message explicitly by index at the moment the preseeds append it, and the loop passes a `-1` sentinel on turns where nothing was preseeded, so `apply_artifact_cache_point` is a no-op then; the CachePoint placed once at phase entry rides forward at the fixed artifact boundary via `all_messages()`. A turn-2+ regression test (a str-content artifact message at an earlier index plus a churny `UserPromptPart` tail, called with the sentinel index) guards against a regression to `[-1]` targeting, since a naive `[-1]` implementation would mutate the tail.
