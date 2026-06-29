---
title: koan's green default pytest skips @skipif live tests and the addopts-excluded
  tests/evals harness; grep and migrate both when changing a production signature
type: procedure
created: '2026-06-28T06:00:19Z'
modified: '2026-06-28T06:00:19Z'
related:
- 0197-redirecting-koans-agent-spawn-to.md
- 0185-run-koans-standard-test-suite-with-bare-pytest-no.md
---

When changing a production function signature or removing a module global in koan, two categories of tests are not exercised by a green `pytest` run and must be found and migrated by hand. First, `@pytest.mark.skipif`-gated live tests (gated on provider keys such as `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`) are skipped in any keyless environment, so they report nothing while still seeding the old code path. Second, the `tests/evals/` DeepEval harness is excluded from the default suite by `addopts = "--ignore=tests/evals"` in `pyproject.toml`, so a bare `pytest` never collects it -- yet `tests/evals/conftest.py` imports and calls production functions (for instance it builds the real config through `load_koan_config`).

The rule: after redirecting a runtime read or changing a shared signature, grep the ENTIRE test tree -- including `tests/evals/` and the skipif-gated modules -- for every call site of the old API, not only the files a plan happened to name, and migrate all of them. Skipping this ships breakage a green default suite cannot see: a home-directory signature change left `tests/evals/conftest.py` calling the old no-argument `load_koan_config()`, which a passing suite never flagged; it was caught only by a manual whole-tree grep. That particular break was further masked by a fail-soft `try/except` that would have silently returned a fallback instead of erroring.
