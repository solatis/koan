---
title: deepeval GeminiModel.a_generate and a_generate_with_schema return (result,
  cost) tuples, not bare results
type: lesson
created: '2026-04-23T16:54:31Z'
modified: '2026-04-23T16:54:31Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
---

This lesson was recorded on 2026-04-23 by Leon during koan's DeepEval migration when his custom metrics fed raw tuple outputs into pydantic parsing and triggered schema-validation errors that read like malformed LLM responses.

Library contract. DeepEval's `GeminiModel` (at `deepeval.models.gemini_model.GeminiModel` in deepeval 3.9.7) returns a two-tuple `(result, cost)` from both `a_generate(prompt: str) -> tuple[str, float]` and `a_generate_with_schema(prompt: str, schema: type[BaseModel]) -> tuple[BaseModel, float]`. The cost is the token-cost estimate computed by DeepEval's model-pricing table; the result is the model output. Other DeepEval model wrappers (e.g. `OpenAIModel`) share this tuple shape; it is not Gemini-specific.

Failure mode. Any call site that treats the tuple return as the bare result -- e.g. `verdict: CriterionVerdict = await JUDGE_MODEL.a_generate_with_schema(prompt, CriterionVerdict)` followed by attribute access on `verdict.verdict` -- fails with an `AttributeError` on the tuple, or (worse) silently passes the tuple through as-is into downstream code that happens to accept a tuple.

Fix. Unwrap at the call site: `verdict, _cost = await JUDGE_MODEL.a_generate_with_schema(prompt, CriterionVerdict)`. In koan's judge metrics this pattern appears in `RubricComplianceMetric.a_measure` and `CrossPhaseCoherenceMetric.a_measure` in `evals/scorers.py`. Any future koan metric that calls a DeepEval model wrapper directly must unwrap; the rule is not DeepEval-documented and is easy to miss. If cost tracking matters, accumulate the second tuple element; otherwise discard with `_cost`.
