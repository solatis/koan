---
title: Custom DeepEval BaseMetric subclasses lose Confident AI dashboard verbose-log
  visibility; DAGMetric is the only observable path
type: lesson
created: '2026-04-23T16:53:42Z'
modified: '2026-04-23T16:53:42Z'
related:
- 0074-deepeval-judge-contract-gevalstrictmodetrue.md
- 0073-deepeval-selected-over-inspect-ai-promptfoo.md
---

This lesson was distilled on 2026-04-23 after Leon migrated koan's eval harness from Inspect AI to DeepEval and then debugged why the Confident AI dashboard showed "No verbose logs available" for every row of the koan suite, despite `RubricComplianceMetric(BaseMetric)` and `CrossPhaseCoherenceMetric(BaseMetric)` producing rich per-criterion reason strings.

Symptom chain. The koan judge contract built per-rubric pass-rate verdicts inside a custom `BaseMetric.a_measure()` that flattened every rubric criterion into a single `self.reason` string. Dashboard rows rendered metric name and pass/fail but no verbose panel content.

Root cause. Leon intercepted the outbound Confident AI API payload on 2026-04-23 and confirmed the verbose strings are transmitted correctly. Inspecting the dashboard frontend showed a CSS class `disableVerbose` that actively hides verbose content for any metric DeepEval did not author -- i.e., any custom `BaseMetric` subclass. The hide is client-side-only; the data is intact on the backend. There is no backend flag, no opt-in, no workaround in user code.

The observable path. DeepEval ships a proper multi-criteria construct at `deepeval.metrics.dag` with node types `BinaryJudgementNode`, `NonBinaryJudgementNode`, `TaskNode`, and `VerdictNode`. Metrics built from this DAGMetric machinery get per-node verbose output with depth levels, criteria, verdicts, and reasons structured through `construct_node_verbose_log()` -- and the dashboard renders that content because it comes from a DeepEval-authored metric class. This is the idiomatic DeepEval path for multi-criteria evaluations; the custom BaseMetric route forfeits dashboard observability regardless of how well the metric body is written.

Lesson for future DeepEval work in koan: if the Confident AI dashboard is part of the observability story, do not subclass `BaseMetric` for multi-criteria judges. Build the judge as a DAGMetric and let DeepEval own the verbose-log rendering. Custom BaseMetric remains viable only when dashboard verbose content is not required.
