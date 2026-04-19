---
title: Eval fixture data model -- one snapshot per fixture, multiple tasks share the
  snapshot, rubrics layered fixture-then-task
type: context
created: '2026-04-19T09:50:06Z'
modified: '2026-04-19T09:50:06Z'
related:
- 0050-eval-benchmark-fixtures-are-manual-git-snapshots-of.md
- 0059-eval-rubric-layout-directory-per-phase-with-fixed.md
---

This entry describes the `evals/fixtures/` directory organization that was established on 2026-04-19 during the per-phase eval framework foundation workflow. On 2026-04-19, Leon decided that a fixture is the unit that owns a snapshot: `evals/fixtures/<fixture>/snapshot.tar.gz` is a `git archive` of koan at a specific commit (stored via git-lfs), tightly coupled to the codebase state a task expects. Each fixture directory hosts one or more tasks at `evals/fixtures/<fixture>/tasks/<task>/task.md`, all of which share the fixture's single snapshot. Snapshots never span fixtures: if a different codebase state is needed, that is a different fixture.

Leon decided that rubrics are the shared/reusable layer, layered in two levels. Fixture-level rubrics at `evals/fixtures/<fixture>/rubrics/<phase>/<section>.md` supply generic grading criteria that apply to every task of that fixture. Optional task-level rubrics at `evals/fixtures/<fixture>/tasks/<task>/rubrics/<phase>/<section>.md` supply task-specific addenda appended to the fixture-level rubric at grade time; if neither exists for a given section, the scorer returns `None` and Inspect AI skips it for that sample. The asymmetry between tasks (isolated per-task.md) and rubrics (shared across tasks of a fixture) exists because rubrics encode generic judgment criteria that reuse across task variants on the same snapshot, while each task's `task.md` carries distinct expected findings.
