---
title: Eval fixture data model -- fixtures carry state, test cases carry workflow/directed_phases/cross-cutting
  rubric
type: context
created: '2026-04-19T09:50:06Z'
modified: '2026-04-27T14:12:59Z'
related:
- 0076-eval-fixture-snapshots-are-self-referential-git.md
- 0059-eval-rubric-layout-directory-per-phase-with-fixed.md
---

This entry describes the `evals/fixtures/` directory organization as reorganized on 2026-04-19 and updated on 2026-04-22 during the Inspect-to-DeepEval migration. The original 2026-04-19 design conflated fixture state with test-case definition; later that same day Leon split the two. A fixture owns a snapshot of the target project's source tree; on 2026-04-22 the snapshot format changed from `evals/fixtures/<fixture>/snapshot.tar.gz` (a `git archive` of koan at a specific commit, tracked via git-lfs) to `evals/fixtures/<fixture>/repo/` (a git submodule pinned to a specific SHA; self-referential for `koan-1`, pinned to the epoch SHA `fc3511684a626fbc33e2806bd089847dd7eea167`). Each fixture directory hosts one or more tasks at `evals/fixtures/<fixture>/tasks/<task>/task.md`, all sharing the fixture's single snapshot. Snapshots never span fixtures: if a different codebase state is needed, that is a different fixture.

On 2026-04-19, Leon decided the fixture layer contains only state: the snapshot, each task's `task.md`, and the invariant per-phase rubrics at `fixtures/<f>/rubrics/<phase>/<section>.md` and `fixtures/<f>/tasks/<t>/rubrics/<phase>/<section>.md`. A separate "test case" layer lives at `fixtures/<f>/tasks/<t>/cases/<slug>.md` and carries the parameters that vary across measurements of the same task: `workflow`, `directed_phases`, and the cross-cutting rubric body. Leon stated: "I think we're mixing datasets / snapshots with test cases." The resulting separation: fixture = state; test case = a distinct run configuration that reuses fixture state. Multiple cases can target the same (fixture, task) pair to measure different directed_phases sequences against a shared snapshot. The previous `fixtures/<f>/rubrics/overall.md` and `tasks/<t>/rubrics/overall.md` files were deleted during the 2026-04-19 reorganization; their content consolidated into the corresponding `cases/full.md` as a concrete migration target. The 2026-04-22 snapshot-format change preserved all of this structure; only the snapshot-storage artifact changed.
