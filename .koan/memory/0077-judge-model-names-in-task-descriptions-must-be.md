---
title: Judge-model names in task descriptions must be verified against the framework's
  model catalog before implementation
type: lesson
created: '2026-04-22T09:17:05Z'
modified: '2026-04-22T09:17:05Z'
---

This entry records a near-miss in the Inspect-to-DeepEval migration of the koan eval harness at `evals/scorers.py`. On 2026-04-22, the migration task description specified `google/gemini-3.1-pro-preview` as the judge model to preserve across the framework swap. Plan-review (run by Leon) caught that no `3.1` family exists in DeepEval's `GEMINI_MODELS_DATA` catalog or in Google's real Gemini lineup -- the string was a fabrication. Leon resolved the target to `gemini-3-pro` (GA release, no `-preview` suffix).

Root cause identified by Leon on 2026-04-22: model version strings referenced in task descriptions were not dereferenced against the vendor SDK or the framework's validated model catalog before encoding them into planning constants. The Inspect-era scorer had already hardcoded the bogus value as `JUDGE_MODEL = "google/gemini-3.1-pro-preview"` at module scope, and the migration task description carried it forward verbatim. Without the plan-review catch, the DeepEval port would have failed at metric-construction time (`GeminiModel(model=...)` validates against `GEMINI_MODELS_DATA` and raises `ValueError` on unknown strings), forcing a mid-implementation model resolution under time pressure.

Correction applied on 2026-04-22: `JUDGE_MODEL = GeminiModel(model="gemini-3-pro")` in `evals/scorers.py` as a module-level constant. The lesson for future framework-integration work: resolve referenced model names against the actual vendor model list or framework catalog at plan time, not runtime; the task description is not a trusted source for model identifiers.
