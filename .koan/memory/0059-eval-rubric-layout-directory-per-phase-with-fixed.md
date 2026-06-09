---
title: Eval rubric layout -- per-phase rubrics invariant across directed-phase variants,
  cross-cutting rubrics live in case files
type: decision
created: '2026-04-19T09:49:51Z'
modified: '2026-04-19T15:19:08Z'
related:
- 0060-eval-fixture-data-model-one-snapshot-per-fixture.md
- 0061-directedphases-fixed-phase-sequence-for-eval.md
---

The rubric layout for the koan-bench Inspect AI task in `evals/` was reorganized on 2026-04-19 after an initial directory-based scheme from earlier the same day proved to conflate fixture state with test-case definitions. On 2026-04-19, Leon decided that per-phase rubrics remain in the directory scheme: `evals/fixtures/<fixture>/rubrics/<phase>/<section>.md` defines fixture-level generic criteria, and `evals/fixtures/<fixture>/tasks/<task>/rubrics/<phase>/<section>.md` optionally supplies a task-specific addendum concatenated to the fixture-level rubric at grade time. The section enum is fixed to four keys per phase: `summary`, `questions`, `artifacts`, `overall`. Per-phase rubrics are invariant across directed-phase variants -- Leon's stated premise was that the same (snapshot, task.md, phase) triple must always produce the same expected output regardless of what phases run before or after.

On the same day, Leon moved cross-cutting (workflow-level) rubrics out of `evals/fixtures/<fixture>/rubrics/overall.md` and into per-case markdown files at `evals/fixtures/<fixture>/tasks/<task>/cases/<slug>.md`. Each case file carries YAML frontmatter declaring `workflow` and `directed_phases` and a body that is the cross-cutting rubric graded by the `workflow_overall` scorer. Leon stated the reason: "the rubrics are actually test cases, but separately we want to execute the workflow in a few directed ways" -- fixture-level state (snapshot + task prompt + invariant per-phase rubrics) is distinct from test-case definitions (workflow + directed_phases + cross-cutting rubric), and the old `overall.md` file mixed the two.

Rejected alternatives on 2026-04-19 during intake: keeping `rubrics/overall.md` as a shared preamble that layers before case-specific cross-cutting text (Leon rejected it to keep case files self-contained); a symmetric fixture-level per-directed-phases overall rubric (Leon declined as unnecessary -- per-case overall at the task level is sufficient); a flat `evals/cases/*.md` tree with fixture+task encoded in frontmatter (Leon rejected it for weaker cohesion with task state); explicit `phases_scored` frontmatter (Leon rejected as duplicating information already in `directed_phases`).
