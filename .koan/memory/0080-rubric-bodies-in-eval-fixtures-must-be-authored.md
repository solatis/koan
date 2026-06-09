---
title: Rubric bodies in eval fixtures must be authored as one-bullet-per-criterion
  for per-bullet judge calls
type: procedure
created: '2026-04-23T06:53:56Z'
modified: '2026-04-23T11:05:15Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0059-eval-rubric-layout-perphase-rubrics-invariant.md
---

This entry records the rubric-authoring procedure for the koan DeepEval harness, covering files under `fixtures/<f>/rubrics/<phase>/<section>.md` and `fixtures/<f>/tasks/<t>/rubrics/<phase>/<section>.md`. On 2026-04-23, Leon accepted that rubric files must be authored so each evaluation criterion is exactly one bullet line. The consumer is `load_rubric_criteria(fixture_dir, task_dir, phase, section)` in `evals/scorers.py`, which splits on bullet markers (`- ` or `* ` after leading-whitespace strip) and returns a `list[str]` that `RubricComplianceMetric.a_measure()` iterates via `asyncio.gather`, one `JUDGE_MODEL.a_generate_with_schema(prompt, CriterionVerdict)` call per criterion.

The rule: each distinct check is its own bullet line; multi-criterion bullets ("X and Y and Z") must be split -- the parser treats each bullet as one atomic criterion passed to the judge verbatim. Prose paragraphs and blank lines produce no criteria and silently lower the effective rubric count. Bullets must be self-contained (no "see item above" or "the preceding list" references), because the judge sees one criterion at a time without surrounding context.

Implications for rubric authoring: the trailing "PASS or FAIL on the last line" directive from the pre-2026-04-23 GEval contract is no longer required for per-(phase, section) rubrics -- the judge returns a structured `CriterionVerdict(passed: bool, reason: str)` per bullet. It IS still required for cross-phase case rubric bodies under `tasks/<task>/cases/<slug>.md`, which are still judged as a single unit via `CrossPhaseCoherenceMetric` using a similar schema-backed judge call over the entire body. Note: DAGMetric was considered on 2026-04-23 morning and abandoned the same afternoon because `DeepAcyclicGraph` rejects multiple BinaryJudgementNode roots; the bullet-per-criterion rule originated under the DAG-based design but carried forward unchanged when the implementation switched to a per-bullet `asyncio.gather` in `RubricComplianceMetric`.
