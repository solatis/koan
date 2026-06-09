---
title: DeepEval selected over Inspect AI, Promptfoo, Braintrust, Langfuse as koan
  eval framework
type: decision
created: '2026-04-22T09:16:21Z'
modified: '2026-04-27T09:02:09Z'
---

This entry documents the framework choice for the koan eval harness under `evals/` in the koan repository. On 2026-04-17, Leon initially selected Inspect AI (UK AISI) over deepeval because deepeval was believed to lack a clean black-box subprocess model. On 2026-04-22, Leon reversed that decision after a deeper framework survey (Inspect AI, DeepEval, Promptfoo, Braintrust, Langfuse, plus Ragas, Patronus, Galileo, Weave, Opik, Phoenix, Helicone, Honeycomb, Traceloop) and selected DeepEval.

Leon's stated rationale for DeepEval: pytest-native discovery (no AST task-gate like Inspect's, which had required a static `@task koan` in `evals/tasks.py` just to let dynamic factories load); per-test-case, per-metric structure maps 1:1 onto per-phase scoring; `GEval(strict_mode=True)` gives binary categorical judgments matching the existing rubric PASS/FAIL last-line contract; `Golden.additional_metadata` is the right home for non-prompt test-row state (`fixture_dir`, `task_dir`, `snapshot_path`, `directed_phases`); Apache-2.0, local-first, no mandatory cloud; per-metric judge-model selection with a shared module-level default.

Leon rejected alternatives on 2026-04-22: Inspect AI (poor TUI/log-viewer UX; brittle AST discovery gate; safety-research focus); Promptfoo (each `exec:`/`file://` provider returns a single output string, not a dict of per-phase artifacts; YAML config scales poorly past hundreds of cases; default GPT-5 judge creates an OpenAI-grading-Anthropic self-preference confound); Braintrust (pricing cliff from free tier to $249/month Pro, and true self-hosting is Enterprise-only with a hybrid data plane that phones home); Langfuse (self-hosting requires Postgres + ClickHouse + Redis + S3, too heavy for a dev-time eval harness; January 2026 ClickHouse acquisition left roadmap direction unproven; better fit for production tracing than offline prompt regression). The remaining surveyed tools were RAG-first, enterprise-priced, observability-first with evals bolted on, source-available rather than OSS, or recently acquired and in maintenance mode.
