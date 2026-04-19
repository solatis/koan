---
title: Inspect AI (UK AISI) selected as koan eval framework over deepeval
type: decision
created: '2026-04-17T12:06:09Z'
modified: '2026-04-17T12:06:09Z'
---

The koan eval framework selection covers the choice of evaluation tooling for the test suite overhaul. On 2026-04-17, Leon evaluated Inspect AI (UK AISI) and deepeval as candidate frameworks and selected Inspect AI. Leon's stated rationale: Inspect AI supports black-box subprocess testing as a first-class concept and provides four clean primitives -- Dataset (frozen fixture collection), Task (spec combining Dataset + Solver + Scorers), Solver (a function that transforms TaskState; koan runs as a subprocess here), and Scorer (grades output; LLM-as-judge supported natively via `model_graded_qa`). deepeval was rejected: it lacks the black-box subprocess model that koan's eval approach requires. The eval framework lives under `evals/` in the koan repository root. The four primitives map to koan as follows: Dataset = frozen koan project snapshots, Solver = subprocess runner against a frozen snapshot, Scorer = LLM-as-judge grading plan artifacts.
