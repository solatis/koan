---
title: Eval rubric layout -- directory-per-phase with fixed section enum and fixture/task
  addendum layering
type: decision
created: '2026-04-19T09:49:51Z'
modified: '2026-04-19T09:49:51Z'
related:
- 0049-eval-solver-answers-all-koan-interactive-gates.md
- 0052-eval-dataset-uses-full-run-fixtures-first-per.md
---

The rubric-driven scorer model for the koan-bench Inspect AI task in `evals/` was established on 2026-04-19 during the per-phase eval framework foundation workflow. On 2026-04-19, Leon decided that rubric authorship follows a three-axis directory scheme: `evals/fixtures/<fixture>/rubrics/<phase>/<section>.md` defines fixture-level generic criteria; `evals/fixtures/<fixture>/tasks/<task>/rubrics/<phase>/<section>.md` optionally supplies task-specific addenda concatenated to the fixture-level rubric at grade time; `evals/fixtures/<fixture>/rubrics/overall.md` defines a workflow-level cross-cutting rubric that sees every phase's data.

Leon fixed the section enum to exactly four keys per phase: `summary`, `questions`, `artifacts`, `overall`. Each key receives a tailored payload slice at grade time (`summary` -> `projection.run.phase_summaries[phase]`; `questions` -> filtered koan_ask_question tool_called events; `artifacts` -> a `{created, modified, all_present}` dict read from disk at workflow completion; `overall` -> the union for the phase). Rubrics are whole files fed to the judge LLM -- section structure comes from directory layout, never from markdown headings, preserving the project invariant that agents do not parse markdown section structure.

Rejected alternatives: a single `rubric.md` per fixture with `## <phase>` top-level sections (Leon rejected it as violating the markdown-parsing invariant); `multi_scorer` composition with a reducer (Leon rejected it because `Task(scorer=[...])` gives native per-column reporting and the reducer would collapse the independent section signals Leon wanted to observe separately); one scorer per phase returning a dict value with dict-keyed metrics (Leon rejected it because debugging a dict-valued judge response is harder than debugging N independent single-value responses).
