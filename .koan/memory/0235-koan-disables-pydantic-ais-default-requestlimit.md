---
title: koan disables pydantic-ai's default request_limit at every agent invocation
  via a single build_usage_limits() gate
type: decision
created: '2026-06-22T02:15:04Z'
modified: '2026-06-22T02:15:04Z'
related:
- 0228-koan-retries-transient-provider-errors-at-the.md
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
- 0026-recoverable-vs-unrecoverable-error-classification.md
---

koan's agent loop (run_agent_loop in koan/agents/loop.py) and the memory-subsystem agents (koan_reflect in koan/memory/retrieval/reflect.py, and the mechanical generate in koan/memory/llm.py) drive pydantic-ai Agent.iter() / Agent.run(). pydantic-ai's UsageLimits defaults request_limit=50 and raises UsageLimitExceeded once a single agent run reaches 50 model requests. Because koan never passed usage_limits, every run silently inherited that cap; a scout exceeded it and the run aborted (the provider-retry boundary classifies UsageLimitExceeded as 'unexpected' and fails fast, so there was no recovery). Leon decided to remove the request cap everywhere rather than tune it, and to route the usage-limits policy through one shared gate, build_usage_limits() in koan/agents/adapter.py, which returns UsageLimits(request_limit=None) (all other usage limits stay at their None defaults); every invocation site passes usage_limits=build_usage_limits(). Rationale: a hard request cap with no recovery path is the same budgeted-mechanism-that-crashes-on-exhaustion anti-pattern koan already rejected for pydantic-ai's ModelRetry budget, and long orchestrator and scout loops needed to be able to run to completion. Alternatives rejected: raising request_limit to a large integer (still an arbitrary cap that re-surfaces the same fail-fast abort on long runs); inlining UsageLimits(request_limit=None) at each call site (duplicates the policy and invites drift -- the single gate is the one source of truth); and reclassifying UsageLimitExceeded as a transient/retryable error (wrong axis -- it is a local config cap, not a network fault, so retrying cannot clear it). The koan_reflect loop keeps its own independent max_iterations cap (MAX_ITERATIONS=10), a deliberate reflect-specific guard that is not a request-count budget. A better long-term replacement -- nudging the model to wrap up as its context window grows -- was discussed but deliberately deferred, so no automatic upper bound on requests per run remains outside reflect's max_iterations.
