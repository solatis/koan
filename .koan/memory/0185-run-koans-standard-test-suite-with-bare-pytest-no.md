---
title: Run koan's standard test suite with bare `pytest` (no path arg); `tests/evals`
  is the live-LLM DeepEval harness excluded via addopts
type: procedure
created: '2026-06-08T01:31:14Z'
modified: '2026-06-08T01:31:14Z'
related:
- 0180-run-and-inspect-koan-through-the-project-venv.md
---

koan's pytest configuration in `pyproject.toml` sets `addopts = "--ignore=tests/evals"`, so the standard test suite is run by invoking `pytest` (or `.venv/bin/python -m pytest`) from the repo root with NO explicit path argument. The `tests/evals/` directory holds the DeepEval rubric/run harness (`tests/evals/test_koan.py`), which executes full koan workflow runs with live LLM calls and judges them; it must be invoked separately via `deepeval test run tests/evals/test_koan.py` (which sets the DEEPEVAL environment variable that activates hyperparameters and Confident AI upload). When verifying an implementation, do NOT pass an explicit path such as `pytest tests/` or a directory argument: an explicit testpath overrides the `--ignore=tests/evals` default and re-collects the eval harness, which then fails (spurious failures) under plain pytest because the live-LLM / Confident-AI machinery is inactive. The functional suite (everything outside `tests/evals`) is fast and hermetic; the eval suite is slow, networked, and gated on provider credentials.
