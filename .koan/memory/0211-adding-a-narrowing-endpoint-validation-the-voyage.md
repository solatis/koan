---
title: Adding a narrowing endpoint validation (the Voyage embedding whitelist 422)
  broke a pre-existing test missed by a verification command scoped to only the changed
  modules
type: lesson
created: '2026-06-12T05:07:39Z'
modified: '2026-06-12T05:07:39Z'
related:
- 0197-redirecting-koans-agent-spawn-to.md
- 0114-safe-deletion-patterns-for-milestone-driven.md
- 0188-verify-executor-scope-by-recent-mtime-find-mmin.md
---

koan config-write endpoints and their tests (`koan/web/app.py:api_config_memory_set`, `tests/test_config_api.py`). A change added a whitelist to the embedding memory binding so that `api_config_memory_set` returns HTTP 422 when a non-Voyage or unrecognized model is bound to the `embedding` kind. The production change was correct, but it broke a pre-existing test, `tests/test_config_api.py::test_memory_set_stores_binding`, which bound a non-Voyage chat model to the embedding role and asserted HTTP 200. The regression was not caught during implementation because the post-change verification command (`pytest tests/test_memory_bindings.py tests/test_model_catalog.py tests/test_provider_config.py tests/memory/`) did not include `tests/test_config_api.py`, and the test-migration sweep enumerated only the new and changed test modules.

Root cause: adding endpoint input-validation that narrows the accepted input has the same test fan-out as deleting a symbol -- every existing test that submits the now-rejected input fails -- but the change was treated as purely additive, so both the verification command and the test sweep were scoped to only the modules being actively edited.

The prevention rule: when a change adds or tightens validation on an endpoint, sweep the test tree for existing tests that submit the input the new rule now rejects (here, tests binding a non-Voyage model to the `embedding` kind) and migrate them, and widen the verification command to include the endpoint's existing test module, not only the modules the change touches.
