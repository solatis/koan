---
title: Prefer real integration/e2e tests over mocks -- one thorough real-system test
  beats a thousand mocked unit tests
type: lesson
created: '2026-04-20T08:44:07Z'
modified: '2026-04-27T09:01:50Z'
related:
- 0051-unit-tests-asserting-llm-prompt-content.md
---

This entry records Leon's testing philosophy for koan, established on 2026-04-20 during work on the `koan_reflect` tool (`koan/memory/retrieval/reflect.py`). The agent had proposed an injectable `llm_client` parameter on `run_reflect_agent()` to support scripted-response unit-level mocking of the Gemini call. Leon corrected the agent with the exact words "i don't care about mockability or testability of the individual calls here, we'll focus on running this through `evals` and that's it." Later the same day, Leon expanded the reasoning: "try to avoid mocks at all costs. I prefer testing real systems, and hate low-value tests. Mocks, to me, are low-value tests. They rarely catch real issues, and it creates a lot of code complexity. It's very easy to have a system with a thousand of unit tests and it's still very much broken. One or two thorough integration tests or e2e tests are much more valuable." Rules applied forward across koan: do not design source code for mockability; do not add injection points whose only purpose is to let a test replace a real dependency; prefer the `evals/` harness and API-key-gated integration tests such as `tests/memory/test_reflect_integration.py` over unit-level mocks of external services. Pure-function helpers that take plain data and return plain data -- such as `_resolve_citations(memory_ids, retrieved)` and `_dispatch_search(index, args, retrieved)` in `reflect.py` -- remain the legitimate unit-test target because they have no dependency to mock. This lesson extends the prompt-content-assertion-test ban recorded in `0051-unit-tests-asserting-llm-prompt-content-deleted.md` into a general ban on mock-driven testing.
